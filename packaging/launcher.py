"""PyInstaller 진입 스크립트. src/autotrader/__main__.py의 main()을 부른다.

src/autotrader/__main__.py를 진입 스크립트로 바로 쓰지 않는 이유: PyInstaller는 진입 스크립트가 있는
폴더를 모듈 검색 경로에 넣는다. src/autotrader/가 들어가면 autotrader/platform 패키지가 표준
라이브러리 platform 모듈을 가린다.
"""

import sys

from autotrader.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
