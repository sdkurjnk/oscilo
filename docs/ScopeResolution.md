# 스코프 해석

변수 이름이 어느 스코프에 속하는지 판정하는 방식과, ENCLOSING 변수를 처리하기 위해 택한 절충안을 정리한다.

관련 코드: `ScopeResolver.resolve`, `ScopeResolver.resolve_cell`, `Domain.py`, `oscilo_engine.c`의 `ScopeType`

---

## 파이썬과 C가 공유하는 도메인 코드

스코프 해석 결과는 파이썬 코드와 C 확장이 함께 쓰는 도메인 코드로 나타낸다. 각 코드의 정수값은 `oscilo_engine.c`의 `ScopeType` enum 한 곳에서만 정의한다. C 확장이 이 값을 파이썬 상수로 내보내고, `Domain.py`의 `Domain`은 그 상수를 그대로 가져다 쓴다.

| 도메인 | 코드 | 의미 |
|---|---:|---|
| `LOCAL` | 0 | 현재 프레임의 지역 변수 |
| `GLOBAL` | 1 | 전역 변수 |
| `ENCLOSING` | 2 | 둘러싼 함수에서 캡처한 변수 |
| `BUILTIN` | 3 | 내장 이름 |
| `NOT_FOUND` | -1 | 이름을 찾지 못함 |

`LOCAL`, `GLOBAL`, `ENCLOSING`만 추적한다. JSONL에는 `ENCLOSING` 변수도 `LOCAL`로 기록한다.

코드 값을 바꾸거나 도메인을 추가할 때는 C 확장을 다시 빌드해야 한다. 그다음 `tests/test_domain_protocol.py`의 계약 테스트와 스코프 조회 관련 테스트가 통과하는지 확인한다.

## LEGB 판정 순서

`ScopeResolver.resolve()`는 런타임 딕셔너리보다 코드 객체의 정적 정보를 먼저 확인한다.

```
co_varnames / co_cellvars 에 있음  → LOCAL
co_freevars 에 있음                → ENCLOSING
f_globals 에 있음                  → GLOBAL
f_builtins 에 있음                 → BUILTIN
그 외                              → NOT_FOUND
```

`co_cellvars`에 있는 변수를 LOCAL로 보는 이유는, 내부 함수가 캡처하는 변수라도 그 변수를 선언한 프레임에서는 지역 변수이기 때문이다. ENCLOSING이 되는 것은 그 변수를 자유 변수로 참조하는 내부 함수 쪽에서뿐이다.

## 선언된 지역 변수는 값이 없어도 바깥 스코프를 가린다

이름이 `co_varnames`나 `co_cellvars`에 있는데 아직 `f_locals`에 없으면, 바깥 스코프를 찾아보지 않고 `NOT_FOUND`를 반환한다.

```python
if var_name in code.co_varnames or var_name in code.co_cellvars:
    if var_name in frame.f_locals:
        return LOCAL, frame.f_locals.get(var_name)
    return NOT_FOUND, None
```

파이썬의 동작과 같다. 함수 안에 그 이름에 대한 대입문이 하나라도 있으면 그 이름은 함수 전체에서 지역 변수이고, 할당 전에 접근하면 전역 값이 아니라 `UnboundLocalError`가 발생한다. 여기서 바깥 스코프로 넘어가면 이름이 같은 전역 변수의 값을 지역 변수의 값처럼 기록하게 된다. 그래서 값이 없는 구간은 `NOT_FOUND`로 둔다.

## ENCLOSING의 소유권 문제

ENCLOSING 변수는 값을 소유하는 것이 프레임이 아니라 클로저 셀이라는 점이 다르다.

```python
def outer():
    n = 0
    def inner():
        nonlocal n
        n += 1
    return inner
```

`inner`를 호출할 때마다 프레임은 새로 생기지만, `n`의 값은 셀에 남아 다음 호출로 이어진다. 또 `outer()`를 두 번 호출하면 코드 객체는 같지만 셀은 서로 다른 두 개가 생긴다. 따라서 변수의 식별자와 이력을 프레임에 묶으면 안 되고, 셀(`id(cell)`)을 키로 써야 한다.

- `VariableTracker._states[id(cell)]`: 셀별 이전 상태(비교 기준)
- `_enclosing_var_ids`: 셀별 변수 ID (`TraceDispatcher`)
- `_enclosing_cell_refs`: 셀에 대한 강한 참조 (`TraceDispatcher`)

셀은 해시할 수 없으므로 세 곳 모두 `id(cell)`을 키로 쓴다. `id()` 값은 객체가 사라지면 다른 객체에 다시 쓰일 수 있다. 그래서 `_enclosing_cell_refs`가 셀을 강한 참조로 붙잡아 두어, 셀이 GC된 뒤 같은 주소에 다른 객체가 생겨 이력이 섞이는 일을 막는다.

## 셀을 찾는 방법 : 휴리스틱

`sys.settrace` 콜백은 프레임만 넘겨준다. 직접 확인해 보니 `frame.f_locals`, `gc.get_referents(frame)`, `PyFrame_GetVar`는 모두 셀이 가리키는 값만 돌려주고 셀 객체 자체는 주지 않았다. 셀 객체는 함수 객체의 `__closure__`를 통해서만 얻을 수 있다.

그래서 `ScopeResolver.resolve_cell`은 거꾸로 호출자 프레임(`frame.f_back`)의 네임스페이스를 살펴, 다음 두 조건을 만족하는 콜러블을 찾는다.

1. 추적 중인 프레임과 같은 코드 객체를 쓴다.
2. 해당 인덱스의 셀에 든 값이 추적 중인 프레임의 현재 값과 같은 객체다.

2번 조건이 필요한 이유는 코드 객체는 같지만 셀이 다른 경우가 있기 때문이다. 또 바운드 메서드도 찾을 수 있도록, 후보에 `__func__`가 있으면 먼저 꺼내서 비교한다.

### 한계

이 방법은 휴리스틱이라 항상 성공하지는 않는다. 호출 시점에 호출자 네임스페이스에서 일반 이름으로 접근할 수 없었던 콜러블은 셀을 찾지 못한다.

- `outer()()`처럼 이름에 바인딩되지 않고 즉시 호출된 경우
- 속성 접근·딕셔너리 조회로 호출된 콜백

이때 `resolve_cell()`은 `None`을 반환한다. 이 `None`은 오류가 아니라 "값을 소유한 셀을 알 수 없음"을 뜻하므로, 호출하는 쪽에서 다른 방식으로 처리해야 한다. 현재 `TraceDispatcher`는 이 경우 셀 대신 프레임을 키로 상태를 저장한다.

`_frame_cell_cache`는 `_UNRESOLVED` 센티널 값으로 "아직 찾아보지 않음"과 "찾아봤지만 없음(`None`)"을 구분한다. 이 구분이 없으면 셀을 찾지 못한 경우 줄마다 다시 찾게 된다.

## BUILTIN과 NOT_FOUND

두 도메인은 추적 대상이 아니다(`TRACKABLE_DOMAINS`에는 `LOCAL`, `GLOBAL`, `ENCLOSING`만 있다). 하지만 판정 결과로는 쓰인다. 이전 상태가 있던 변수가 이 도메인으로 바뀌면 `deleted`, 이전 상태가 없었으면 `not_found`로 처리한다.
