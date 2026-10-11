# Lift Trace

[English](README.md) · [한국어](README.ko.md) · [日本語](README.ja.md)

**beatmania IIDX INFINITAS**에서 누른 건반과 스크래치 움직임을 OBS에 보여주는 프로그램입니다. 건반을 누르거나 스크래치를 돌리면 게임의 판정선 아래로 **입력 노트**가 떨어집니다. 입력 노트는 컨트롤러 조작을 그린 것이며, 게임 채보를 읽어서 표시하는 노트는 아닙니다.

**프로토타입입니다.** Windows 10/11(64비트)용이며 한국어·일본어·영어를 지원합니다.

코드와 문서 작성에 AI 도구를 폭넓게 활용했습니다. 현재 초기 시험판이며, [검증 현황과 남은 확인 사항](docs/VALIDATION.md)에 확인한 내용과 실제 사용·사람의 검토가 필요한 부분을 구분해 안내합니다. 이 문서는 영어로 작성되어 있습니다.

## 프로그램을 사용하고 싶어요

**프로그래밍, Python 설치, 명령어 입력이 필요하지 않습니다.**

**[Windows 앱 다운로드](https://github.com/d0vetam3r/lift-trace/releases/latest)**에서 최신 버전을 받으세요.

1. 이 GitHub 페이지에서 **Releases**를 열고 최신 버전의 **Assets**를 펼칩니다.
2. 이름이 `lift-trace-windows-x64-`로 시작하고 `.zip`으로 끝나는 파일을 받습니다. 중간 숫자는 버전이므로 달라질 수 있습니다.
3. 받은 파일을 오른쪽 클릭하고 **압축 풀기**를 누릅니다. 압축을 푼 **LiftTrace** 폴더에서 **LiftTrace.exe**를 더블클릭합니다.
4. [처음부터 따라 하는 사용 안내](docs/USER_GUIDE.ko.md)를 보고 게임 수치 입력, 컨트롤러 설정, OBS에 주소 붙여넣기를 진행합니다.

누를 버튼과 확인할 결과를 순서대로 안내합니다. LIFT 값을 넣으면 표시 높이가 자동으로 계산되며, 높이를 직접 정할 수도 있습니다. 게임이 1080p 화면 전체에 보이는 구성에서는 레인 크기를 맞추는 버튼을 누른 뒤, 계산된 가로·세로 위치를 OBS에 복사해 배치합니다.

OBS Studio, INFINITAS, 호환 컨트롤러는 별도로 필요합니다. 압축을 푼 폴더의 파일은 함께 보관하세요. 실행되지 않으면 [문제 해결](docs/USER_GUIDE.ko.md#문제-해결)을 확인하세요.

## 소스코드에 기여하고 싶어요

저장소를 복제하거나 Releases의 `lift-trace-source-*.zip`을 받으세요. `*`는 버전 번호입니다. Windows 앱도 같은 소스코드로 만듭니다.

[개발 가이드](docs/DEVELOPMENT.md) · [기여 안내](CONTRIBUTING.md) · [기술 참고](docs/REFERENCE.md) · [검증 현황](docs/VALIDATION.md) · [릴리스 안내](docs/RELEASING.md)

개발 문서는 영어입니다. source ZIP과 GitHub의 “Source code”는 개발자용이며, 프로그램 사용자는 위의 Windows ZIP을 선택하세요.

## 프로젝트 소개

현재 표시는 **1920 × 1080 OBS 화면 전체에 게임이 보이는 구성**을 기준으로 합니다. 표시 높이를 바꿔도 계산된 낙하 속도는 바뀌지 않습니다. 위치와 타이밍은 실제 게임 화면에 맞춰 조절해야 합니다. 게임의 판정이 아닌 입력을 표시합니다.

프로젝트 코드는 [MIT 라이선스](LICENSE)입니다. 함께 배포되는 런타임에는 각자의 라이선스가 적용됩니다. [변경 이력](CHANGELOG.md) · [보안과 로컬 데이터](SECURITY.md)

Lift Trace는 독립 프로젝트이며 KONAMI, DJ DAO/GAMO2, OBS Project와 제휴하거나 이들의 승인을 받은 제품이 아닙니다. 제품명은 각 소유자에게 속합니다.
