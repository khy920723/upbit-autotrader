# CI 변경 제안

클라우드 세션은 `.github/workflows/`를 수정할 수 없다. 변경이 필요하면 여기에 이유와 변경안(diff)을 적는다. 사용자가 로컬에서 반영하고 해당 항목을 지운다.

## 1. 커버리지 측정 (2단계에서 반영)

- 이유: 테스트 전략의 커버리지 기준(core 80%, 위험·주문 관리 분기 100%)을 CI에서 확인하려고.
- 전제(2단계에서 충족): dev 그룹에 pytest-cov가 있고, `pyproject.toml`의 `[tool.coverage.run]`이 측정 대상(`source = ["autotrader"]`)과 분기 측정(`branch = true`)을 정한다.
- 변경: ci.yml의 Test 단계를 `uv run pytest -q --cov --cov-report=term-missing`로 바꾼다. 대상과 분기 설정은 pyproject를 따른다. 기준 강제(`--cov-fail-under`)는 코드가 쌓인 뒤 정한다. 2단계 코드 기준 줄·분기 커버리지는 93%다(클라우드 세션 측정).

```diff
       - name: Test
         if: steps.project.outputs.exists == 'true'
         env:
           QT_QPA_PLATFORM: offscreen
-        run: uv run pytest -q
+        run: uv run pytest -q --cov --cov-report=term-missing
```
