# 상태 자료구조와 상호작용

`TraceDispatcher`는 여러 개의 dict를 들고 있다. 이 문서는 각 dict가 무엇을 맡고 있고, 서로 어떻게 맞물리며, 언제 비워지는지를 정리한다.

관련 코드는 `../src/oscilo/TraceDispatcher.py`의 `__init__`, `register`, `unregister`, `stop`, `_stop_tracing`, `_relevant_for`, `_check_and_log_local`/`_global`/`_enclosing`, `_log_event`와 `src/oscilo/VariableTracker.py`의 `check_owned`이다.

---

## 세 개의 층

dict들은 크게 세 가지 질문에 답한다.

| 층 | 자료구조 | 답하는 질문 |
|---|---|---|
| 등록 | `_registered_local`, `_registered_global` | 이 변수는 이미 등록돼 있는가? |
| 선별 | `_frame_cache`, `_tracker_codes`, `_tracker_globals` | 이 프레임을 추적해야 하는가? |
| 상태 | `VariableTracker._states` | 이 변수의 직전 값은 무엇이었는가? |

세 층은 수명이 다르다. 등록 정보는 tracker와 함께 살고, 선별 캐시는 tracker 목록이 바뀔 때마다 버려진다. 비교 상태는 tracker가 들고 있되 프레임, 셀, 전역 같은 스코프 인스턴스 단위로 나뉘어 저장된다.

이 밖에 로그에 찍을 식별자를 담는 `_global_var_ids`와 `_enclosing_var_ids`, 정리할 때 쓰는 `_enclosing_cell_refs`, `_tracker_cells`, `_frame_states`, `_frame_cell_cache`가 있다. 아래에서 차례로 설명한다.

---

## 등록 층: 같은 변수는 tracker 하나

`register()`가 같은 변수에 여러 번 불리는 것은 정상이다. 재귀 함수나 반복문 안에서 등록하면 매번 다시 불리기 때문이다. 그때마다 tracker를 새로 만들면 `_trackers`가 끝없이 늘어나고 한 변수의 이력이 여러 갈래로 쪼개진다.

그래서 dedup 키로 이미 등록된 tracker가 있는지 먼저 찾는다.

```python
if is_local:
    dedup_key = (varName, code)                  # _registered_local
else:
    dedup_key = (varName, id(frame.f_globals))   # _registered_global
```

키 모양이 다른 것은 같은 변수를 판단하는 기준이 다르기 때문이다. 지역 변수는 code 객체 단위로 본다. 같은 함수를 몇 번 호출하든 그 함수의 `x`는 tracker 하나를 공유하고, 호출마다 다른 값은 아래 상태 층에서 프레임별로 나눠 저장한다. 전역 변수는 모듈 네임스페이스, 곧 `f_globals` dict 단위로 본다. 어느 함수에서 등록하든 같은 모듈의 같은 전역이면 하나다. dict는 해시가 되지 않으므로 `id()`를 쓴다.

키가 이미 있으면 기존 tracker를 다시 쓰고 새로 만드는 과정은 건너뛴다. 이 결과는 `is_new_tracker`로 넘어가서, 조상 프레임을 탐색할 때 일찍 멈출지 정하는 데 쓰인다. 자세한 내용은 [프레임 부착 전략](FrameAttachment.md)에 있다.

### 새 tracker를 만들 때 함께 기록하는 것

새 tracker가 생기면 dedup 맵과 함께 tracker에서 스코프를 거꾸로 찾는 역방향 맵도 채운다.

| 경우 | 정방향 (dedup) | 역방향 | 추가 |
|---|---|---|---|
| LOCAL | `_registered_local[(varName, code)] = tracker` | `_tracker_codes[tracker] = code` | 없음 |
| GLOBAL | `_registered_global[(varName, id(globals))] = tracker` | `_tracker_globals[tracker] = globals` | `_global_var_ids[tracker] = call_id` |

역방향 맵은 두 군데에서 쓰인다. 아래 선별 층에서 스코프가 같은지 확인할 때, 그리고 `unregister()`에서 tracker만 가지고 dedup 키를 다시 만들어 낼 때다.

`_tracker_globals`가 globals dict 자체를 들고 있다는 점도 의미가 있다. dict가 살아 있는 동안에는 dedup 키에 쓴 `id()` 값이 다른 객체에 재사용될 수 없기 때문이다.

전역 변수에만 있는 `_global_var_ids`는 로그의 `var_id`를 등록 시점에 고정하는 역할을 한다. `ensure_context(frame)`으로 등록 프레임의 `call_id`를 받아 저장해 두고, 이후 어느 프레임에서 값이 바뀌든 이 값을 `var_id`로 쓴다. 왜 그렇게 하는지는 뒤의 "전역 변수는 왜 하나의 타임라인인가"에서 설명한다.

---

## 선별 층: 두 단계로 거른다

이 프레임에 관련된 tracker가 있는지는 `"call"` 이벤트마다, 그리고 추적 중인 프레임에서는 매 줄마다 묻는 질문이다. 그래서 먼저 싼 검사로 후보를 좁히고, 그다음 정확한 검사로 확정한다.

### 1단계: `_frame_cache`

```python
names = set(code.co_varnames) | set(code.co_cellvars) | set(code.co_freevars)
local_candidates  = [t for t in self._trackers if t.varName in names]
global_candidates = [t for t in self._trackers if t.varName not in names]
```

tracker의 변수 이름이 이 code 객체의 지역 이름 집합에 들어 있는지만 본다. code 객체의 정적 정보만 쓰기 때문에 같은 code 객체라면 어느 프레임에서든 결과가 같고, 그래서 `f_code`를 키로 안전하게 캐시할 수 있다.

프레임마다 달라질 수 있는 `f_globals`는 캐시에 넣지 않는다. 그것은 2단계에서 현재 프레임을 보고 판단한다.

### 2단계: `_tracker_codes`와 `_tracker_globals`

1단계는 이름만 보므로 다른 모듈에 있는 같은 이름의 함수나 같은 이름의 전역도 통과한다. 2단계에서는 등록 당시의 실제 스코프와 `is`로 비교해 이런 경우를 걸러낸다.

```python
local_relevant  = [t for t in local_candidates
                   if self._tracker_codes.get(t) is frame.f_code]
global_relevant = [t for t in global_candidates
                   if self._tracker_globals.get(t) is frame.f_globals]
```

이름이 아니라 객체가 같은지를 보기 때문에 이름이 같은 함수나 모듈이 섞이지 않는다. 같은 code 객체가 서로 다른 globals에서 실행되는 경우에도 1단계 캐시는 함께 쓰지만, 전역 변수 tracker는 현재 `frame.f_globals`가 등록 당시의 dict와 같을 때만 선택된다.

이 정보를 tracker가 아니라 dispatcher가 들고 있는 것은, tracker가 등록한 그 스코프에만 적용되도록 묶어 두기 위해서다.

### 캐시 무효화

`_frame_cache`는 `_trackers`에서 파생된 캐시라서 목록이 바뀌면 통째로 비운다. 새 tracker를 만든 `register()`와 `unregister()`가 여기에 해당한다. dedup으로 기존 tracker를 다시 쓴 경우에는 목록이 그대로이므로 비우지 않는다.

---

## 상태 층: 비교 기준은 tracker가 들고 있다

변수의 직전 값은 `VariableTracker._states`에 있다. dispatcher는 값을 직접 들고 있지 않고, 어떤 key로 검사할지만 넘긴다.

```python
def check_owned(self, frame, domain, key):
    prev_state = self._states.get(key)
    event_name, new_state = self.evaluate(frame, domain, self.varName, prev_state)
    if new_state is None:
        self._states.pop(key, None)
    else:
        self._states[key] = new_state
    return event_name, new_state
```

dispatcher의 세 진입점은 도메인에 따라 다른 key를 넘긴다.

| 도메인 | 진입점 | key | 이유 |
|---|---|---|---|
| LOCAL | `_check_and_log_local` | `frame` | 호출(재귀 포함)마다 값이 따로 있음 |
| GLOBAL | `_check_and_log_global` | `GLOBAL_STATE_KEY` | 모든 프레임이 하나의 타임라인을 공유 |
| ENCLOSING | `_check_and_log_enclosing` | `id(cell)`, 셀을 못 찾으면 `frame` | 값의 주인이 클로저 셀 |

이렇게 tracker 하나가 자기 변수의 모든 인스턴스를 `_states`에 key별로 들고 있으니 재귀 호출도 프레임별로 나뉜다. dispatcher는 판정과 저장에는 관여하지 않고, 어느 key로 보낼지와 무엇을 로그에 남길지, 어떤 `var_id`를 붙일지만 맡는다.

세 진입점은 모두 `_guarded_check_and_log`로 감싸서 호출된다. 추적 중인 값의 `__eq__`가 예외를 던지는 식으로 검사가 실패해도 그 tracker의 그 이벤트 하나만 건너뛰고, 사용자 프로그램으로는 예외가 새어 나가지 않는다. 이 부분은 [변경 감지 전략](ChangeDetection.md)의 예외 격리 절에 자세히 나와 있다.

### 전역 변수는 왜 하나의 타임라인인가

전역 변수는 어느 함수에서 바꾸든 같은 변수다. 이를 프레임별로 저장하면 `foo`에서 바꾼 값이 `bar`의 비교 기준에 반영되지 않아서, 같은 변경이 두 번 찍히거나 아예 빠지게 된다. 그래서 전역 변수는 `GLOBAL_STATE_KEY` 하나로 상태를 하나만 둔다.

`var_id`를 고정하는 것도 같은 이유다. `_global_var_ids`에 등록 프레임의 `call_id`를 저장해 두고 이후 어느 프레임에서 바뀌든 그 값을 쓰기 때문에, 로그를 읽을 때 이 이력이 한 변수의 것으로 이어진다.

### `var_id`를 고르는 규칙

`_log_event`는 `var_id`를 정할 때 먼저 ENCLOSING 변수이고 셀을 찾았는지 본다. 그렇다면 셀마다 한 번 발급해 둔 ID(`_enclosing_var_ids`)를 쓴다. 그게 아니고 전역 변수 tracker라면 등록 시점에 고정해 둔 ID(`_global_var_ids`)를 쓴다. 둘 다 아니라면, 즉 지역 변수이거나 셀을 찾지 못한 ENCLOSING 변수라면 이벤트가 관측된 프레임의 `call_id`를 쓴다.

ENCLOSING의 셀 ID는 `CallContextManager.next_id()`로 받는다. `call_id`와 같은 카운터를 쓰므로 두 ID가 겹치지 않는다. 자세한 내용은 [호출 컨텍스트 트리](CallContext.md)를 참고한다.

---

## 흐름

### `register()`

`register()`는 먼저 `resolve()`로 변수의 도메인을 판정하고, dedup 키로 `_registered_local`이나 `_registered_global`을 조회한다. 이미 있으면 그 tracker를 다시 쓰고 `is_new_tracker`는 `False`가 된다.

없으면 `VariableTracker`를 새로 만들어 `_trackers`에 넣는다. 지역 변수라면 `_registered_local`과 `_tracker_codes`를 기록하고, 전역 변수라면 `_registered_global`과 `_tracker_globals`를 기록한 뒤 `ensure_context(frame)`으로 받은 `call_id`를 `_global_var_ids`에 고정한다. 그다음 `_frame_cache`를 비운다.

이어서 `_start_tracing()`으로 훅을 건다. `sys.settrace(_trace_calls)`는 처음 한 번만 호출된다. 그리고 `_ensure_frame_tracking(frame)`으로 등록 프레임에 트레이서를 붙여 `_frame_states`에 표시하고, `_ensure_active_ancestor_tracking(frame, is_new_tracker)`로 `f_back`을 따라 올라가며 관련 있는 조상 프레임에도 트레이서를 붙인다. 이 탐색은 `<module>`에서 멈춘다.

마지막으로 도메인에 맞는 `_check_and_log_*`를 불러 `check_owned`로 현재 값을 검사한다. 처음 보는 값이므로 여기서 `init` 이벤트가 기록된다.

### 실행 중인 한 줄

추적 중인 프레임에서 한 줄이 실행되면 `line` 이벤트가 라인 트레이서로 들어온다. 트레이서는 `_process_frame(frame)`을 부르고, 여기서 `_relevant_for(frame)`가 `_frame_cache`로 후보를 뽑은 뒤 `_tracker_codes`와 `_tracker_globals`로 확정한다. 확정된 tracker마다 도메인을 다시 해석해서 지역 변수는 `_check_and_log_local`로 프레임을 key로, 전역 변수는 `_check_and_log_global`로 `GLOBAL_STATE_KEY`를 key로, ENCLOSING 변수는 `_check_and_log_enclosing`으로 셀을 key로 보낸다. 검사 결과가 `init`, `updated`, `deleted` 중 하나라면 `_log_event`가 `HistoryBuffer.append()`로 레코드를 남긴다.

`return` 이벤트에서도 정리하기 전에 `_process_frame`을 한 번 더 돌려서 마지막 줄에서 일어난 변경을 놓치지 않는다.

### 정리

프레임이 진짜로 끝나면 `_forget_frame_local_states(frame)`가 지역 변수 tracker들에서 그 프레임의 상태를 지우고(`tracker.forget(frame)`), `_frame_states`와 `_frame_cell_cache`에서 그 프레임을 뺀다. ENCLOSING 상태는 지우지 않는다. 클로저는 자기를 정의한 프레임이 끝난 뒤에도 호출될 수 있기 때문이다. 제너레이터나 코루틴이 `yield`로 멈춘 경우에는 다시 실행될 때 같은 비교 기준을 써야 하므로 아무것도 지우지 않는다.

`unregister(tracker)`는 먼저 tracker를 `_trackers`에서 빼고 `tracker.reset()`으로 그 tracker의 `_states`를 통째로 비운다. 그다음 역방향 맵을 `pop`해서 code나 globals를 꺼내고, 그것으로 dedup 키를 다시 만들어 `_registered_local`이나 `_registered_global`에서 지운다. tracker는 둘 중 한쪽에만 등록돼 있으므로 실제로는 한쪽만 지워진다. `_global_var_ids`에서도 그 tracker를 지우는데, 지역 변수 tracker라면 키가 없으니 아무 일도 일어나지 않는다. 이어서 `_tracker_cells`에 기록해 둔 셀 목록으로 `_enclosing_var_ids`와 `_enclosing_cell_refs`를 정리한다. 이 목록이 없으면 어느 셀이 어느 tracker의 것인지 알 수 없어서 다른 tracker의 셀까지 지우게 된다. 끝으로 `_frame_cache`를 비우고, 남은 tracker가 없으면 `_stop_tracing()`을 부른다.

`stop()`은 남아 있는 모든 tracker를 `reset()`하고 `_trackers`를 비운 뒤 `_stop_tracing()`을 부른다.

`_stop_tracing()`은 `sys.settrace(None)`으로 훅을 떼고, dispatcher가 들고 있는 dict와 캐시를 모두 비운 다음 `CallContextManager.clear()`로 호출 컨텍스트도 비운다. tracker를 `reset()`하는 것은 이 함수가 아니라 `stop()`과 `unregister()`가 하는 일이다.

---

## 수명 요약

| 자료구조 | 키 | 값 | 지워지는 때 |
|---|---|---|---|
| `_registered_local` | `(varName, f_code)` | tracker | `unregister`, `_stop_tracing` |
| `_registered_global` | `(varName, id(f_globals))` | tracker | `unregister`, `_stop_tracing` |
| `_tracker_codes` | tracker | `f_code` | `unregister`, `_stop_tracing` |
| `_tracker_globals` | tracker | `f_globals` dict | `unregister`, `_stop_tracing` |
| `_global_var_ids` | tracker | 등록 시점 `call_id` | `unregister`, `_stop_tracing` |
| `_tracker_cells` | tracker | `id(cell)` 집합 | `unregister`, `_stop_tracing` |
| `_enclosing_var_ids` | `id(cell)` | 셀별 `var_id` | `unregister`, `_stop_tracing` |
| `_enclosing_cell_refs` | `id(cell)` | 셀에 대한 강한 참조 | `unregister`, `_stop_tracing` |
| `_frame_cache` | `f_code` | 지역/전역 후보 목록 | tracker 목록이 바뀔 때, `_stop_tracing` |
| `_frame_states` | frame | 추적 표시 | 프레임이 진짜로 끝날 때, `_stop_tracing` |
| `_frame_cell_cache` | frame | `id(cell)` 또는 `None` | 프레임이 진짜로 끝날 때, `_stop_tracing` |
| `VariableTracker._states` | frame, `id(cell)`, `GLOBAL_STATE_KEY` | 직전 상태 | 지역 변수는 프레임이 끝날 때 `forget`, 전체는 `unregister`나 `stop`의 `reset` |

비교 상태는 tracker가 갖고, dispatcher는 식별자와 정리용 기록, 프레임 추적 표시만 갖는다. ENCLOSING 상태가 프레임이 아니라 셀에 묶이는 이유는 [스코프 해석](ScopeResolution.md)에 적어 두었다.
