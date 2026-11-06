import copy
import json

class HistoryBuffer:
    _DOMAIN_LABELS = {
        0: "LOCAL",
        1: "GLOBAL",
        2: "ENCLOSING",
    }
    _UNKNOWN_DOMAIN_LABEL = "UNKNOWN"

    def __init__(self):
        self._history = []

    def append(self, name, var_id, data, event, domain=None, line=None, func=None, call_id=None, parent_call_id=None, call_depth=None,):
        # JSONL을 읽기 쉽게 domain을 라벨로 저장한다.
        history_entry = {
            "name": name,
            "var_id": var_id,
            "data": data,
            "event": event,
            "domain": self._get_domain_label(domain),
            "line": line,
            "func": func,
            "call_id": call_id,
            "parent_call_id": parent_call_id,
            "call_depth": call_depth,
        }
        self._history.append(history_entry)

    def _get_domain_label(self, domain):
        # 매핑에 없는 domain은 UNKNOWN으로.
        return self._DOMAIN_LABELS.get(domain, self._UNKNOWN_DOMAIN_LABEL)

    def getHistory(self):
        # 호출자가 내부 이력을 변형 못 하도록 깊은 복사본을 반환한다.
        return copy.deepcopy(self._history)

    def write(self, filename):
        # 기록이 없으면 파일을 만들지 않는다.
        if not self._history:
            return

        with open(filename, "w", encoding="utf-8") as file:
            for entry in self._history:
                json_line = self._serialize_entry(entry)

                # repr()조차 실패해서 아예 표현 불가능한 엔트리는 파일 전체를 망가뜨리지 않도록 건너뛴다.
                # 이슈 #52 참고.
                if json_line is None:
                    continue

                file.write(json_line + "\n")

    def _serialize_entry(self, entry):
        # 일반적인 경우: 엔트리가 이미 그대로 JSON 직렬화 가능하다.
        try:
            return json.dumps(entry, ensure_ascii=False)
        except Exception:
            pass

        # 폴백: JSON 네이티브가 아닌 값(예: `data`의 커스텀 객체)을 repr()로 대체해
        # 나머지 필드는 보존하고 레코드 전체를 잃지 않는다.
        try:
            return json.dumps(entry, ensure_ascii=False, default=repr)
        except Exception:
            # repr() 폴백마저 실패(예: __repr__가 예외, 또는 default로도 처리 못 하는 dict key).
            # 이 엔트리 하나만 포기한다.
            return None

    def clearBuffer(self):
        self._history.clear()