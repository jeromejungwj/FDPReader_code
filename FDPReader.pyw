"""더블클릭·연결 프로그램용 실행 파일. 배포용 exe 의 진입점이기도 함."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()  # exe 안에서 렌더 프로세스가 앱을 다시 띄우지 않게
    if sys.argv[1:2] == ["--fdp-watchdog"]:  # exe 에는 python 이 없어 자기 자신을 감시 프로세스로 띄움
        from features.sign import watchdog

        sys.exit(watchdog.main())
    from app.__main__ import main

    sys.exit(main())
