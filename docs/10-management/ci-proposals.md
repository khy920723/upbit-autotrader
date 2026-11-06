# CI 변경 제안

클라우드 세션은 `.github/workflows/`를 수정할 수 없다. 변경이 필요하면 여기에 이유와 변경안(diff)을 적는다. 사용자가 로컬에서 반영하고 해당 항목을 지운다.

1번(커버리지 측정)은 ci.yml에 반영되어 지웠다(main 5858e59).

## 2. Windows에서 네트워크 차단·웹소켓 테스트 돌리기 (3단계 3b 제안)

- **이유:** 테스트 중 실제 네트워크 차단(`tests/fakes/network_guard.py`, QA R17-02)은 Windows Proactor 루프의 연결·UDP 송신 경로(`asyncio.windows_events.IocpProactor.connect`·`sendto`)를 따로 감싼다. 이 경로는 Windows에서만 돌고, 지금 CI의 windows 작업은 빌드와 `--self-test`만 해서 한 번도 실행된 적이 없다. 웹소켓 루프백 통합 테스트(`tests/integration/test_websocket_loopback.py`)도 Windows 이벤트 루프에서 확인되지 않았다.
- **변경안(`.github/workflows/build-exe.yml`의 windows 작업, "Install dependencies" 뒤):**

```diff
       - name: Install dependencies
         if: steps.spec.outputs.exists == 'true'
         run: uv sync --locked
+
+      - name: Windows-only tests (network guard, websocket loopback)
+        if: steps.spec.outputs.exists == 'true'
+        env:
+          QT_QPA_PLATFORM: offscreen
+        run: uv run pytest -q tests/unit/test_network_guard.py tests/integration/test_websocket_loopback.py
```

- 시간: 리눅스에서 두 파일이 약 3초다. 실패하면 Windows 경로의 차단이나 루프백 연결에 문제가 있다는 뜻이므로 빌드 전에 멈추는 것이 맞다.
