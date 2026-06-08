# [프로젝트 명]: VTTT(Vanishing-Tic-Tac-Toe)---3×3 디스플레이 모듈을 활용한 강화학습 기반 배니싱 틱택토 게임판 개발 

## 1. 프로젝트 개요 (Overview)

- **주요 개발 분야**:
  - 배니싱 틱택토 인공지능 모델 개발 (Development of a Vanishing Tic-Tac-Toe AI Model)
  - 3x3 디스플레이 제어 (3x3 Display Control)
  - 화면별 그래픽 요소 개발 (Development of Graphic Elements Per Screen)

- **참여 연구원**:
  - [김동균]
  - [김민서]
  - [김찬우]
  - [엄지현]

## 2. 디렉토리 구조 (Directory Structure)

프로젝트의 일관성을 위해 아래의 디렉토리 구조를 따름

```
.
├── README.md
├── requirements.txt         # 프로젝트 의존성 패키지 목록
├── data/
│   ├── raw/                 # 원본 데이터 (Git LFS 또는 외부 저장소 사용 권장)
│   └── processed/           # 전처리된 데이터
├── notebooks/               # 데이터 탐색, 시각화, 빠른 프로토타이핑을 위한 주피터 노트북
├── display/                 # 디스플레이 제어 관련 코드
├── src/
│   ├── data_loader.py       # 데이터셋 및 데이터로더 정의
│   ├── models/              # 모델 아키텍처 정의 (예: lstm_model.py, transformer_model.py)
│   ├── trainer.py           # 모델 학습 및 평가 로직
│   ├── predict.py           # 학습된 모델로 추론을 수행하는 스크립트
│   └── utils.py             # 공통으로 사용되는 헬퍼 함수
├── configs/                 # 실험별 설정 파일 (YAML, JSON 형식)
├── scripts/                 # 실험 실행을 위한 쉘 스크립트
└── results/
    ├── saved_models/        # 학습된 모델 가중치 (.pt, .pth, .bin)
    └── logs/                # 학습 로그 및 실험 결과
```

## 3. 코딩 컨벤션 (Coding Convention)

### 3.1. 네이밍 규칙 (Naming Convention)

- **변수 및 함수**: `snake_case` (e.g., `calculate_loss`)
- **클래스**: `PascalCase` (e.g., `EmotionClassifier`)
- **상수**: `UPPER_SNAKE_CASE` (e.g., `LEARNING_RATE`)

### 3.2. Docstrings

모든 모듈, 함수, 클래스, 메서드에는 **Google Python Style**의 Docstring을 작성

**예시**:
```python
def predict_action(state: list, model: nn.Module) -> int:
    """현재 게임 상태에서 AI의 다음 수를 예측합니다.

    Args:
        state (list): 현재 배니싱 틱택토 보드 상태.
        model (nn.Module): 학습된 강화학습 모델.

    Returns:
        int: AI가 선택한 다음 위치 (0~8).
    """
    # ... function logic ...
    action = 4
    return action
```

## 4. 실험 및 모델 관리 (Experiment & Model Management)

### 4.1. 실험 설정

실험에 필요한 모든 하이퍼파라미터(learning rate, batch size 등)는 `configs/` 디렉토리의 YAML 파일로 관리

**예시 (`configs/vanishing_tictactoe_rl.yaml`)**:
```yaml
model:
  name: "Vanishing_TicTacToe_RL"
  architecture: "DQN"

train:
  episodes: 30000
  batch_size: 64
  learning_rate: 1e-3

environment:
  name: "Vanishing_TicTacToe_Env"
  board_size: 3
```

### 4.2. 성능 지표 (Performance Metrics)

각 과제에 대해 아래의 핵심 지표를 `results/logs/`에 기록하고, Pull Request에 반드시 포함하여 보고

- **게임 AI 성능 지표**:
  - **Win Rate (승률)**
  - **Draw Rate (무승부율)**
  - **Lose Rate (패배율)**
  - **Average Reward (평균 보상)**
  - **Episode Length (평균 게임 길이)**

### 4.3. 모델 설명 및 저장

- 학습된 모델은 `results/saved_models/`에 저장
- **파일명 규칙**: `{모델명}_{환경명}_{yyyymmdd}.pt`
- **예시**: `vttt_dqn_v1_20260321.pt`
- 모델 아키텍처는 `src/models/`에 명확하게 정의된 파이썬 코드로 관리

### 4.4. 실험 환경 기록 및 보고 (Logging and Reporting Environment)


각 `feature` 브랜치에서 새로운 모델 학습이나 주요 실험을 진행할 경우, 브랜치 내에 **`experiment_report.md`** 파일을 생성하여 아래 가이드를 따라 실험 내용을 기록

---

#### **보고서 작성 가이드 (`experiment_report.md`에 포함될 내용)**

1.  **실험 보고서 파일 생성**
    - 자신의 `feature/{도메인}/{기능명}` 브랜치 내에 `experiment_report.md` 파일을 생성합니다. 이 파일은 Git 추적에 포함

2.  **환경 정보 템플릿 복사 및 작성**
    - 아래의 **하드웨어 환경**과 **소프트웨어 환경** 표 템플릿을 `experiment_report.md` 파일에 복사하고, 실제 실험을 진행한 환경에 맞게 내용을 채움

3.  **실험 내용 요약 추가**
    - 표 아래에 실험 목표, 과정, 결과 요약 등을 자유롭게 기술하여 컨텍스트를 쉽게 파악할 수 있도록 함
    - **예시**:
      ```
      - 배니싱 틱택토 환경에서 DQN 기반 모델 학습
      - 말이 사라지는 규칙을 반영한 상태 표현 설계
      - 랜덤 정책 대비 승률 35% → 78%로 향상
      ```

4.  **Pull Request에 첨부**
    - `develop` 브랜치로 Pull Request(PR)를 생성할 때, 본문에 이 보고서 파일(`experiment_report.md`)의 내용을 직접 붙여넣거나 파일 링크를 포함하여 쉽게 확인할 수 있도록 함

---

#### **템플릿: 하드웨어 환경 표**
*(아래 표를 복사하여 `experiment_report.md` 파일에 사용)*

| 항목 (Item)   | 사양 (Specification)                     |
| :------------ | :--------------------------------------- |
| **서버 (Server)** | `DGX-A100-Server-01`                     |
| **CPU**         | `Intel(R) Xeon(R) Gold 6240R CPU @ 2.40GHz` |
| **GPU**         | `NVIDIA A100-SXM4-40GB (x1)`             |
| **메모리 (RAM)**  | `256 GB`                                 |

---

#### **템플릿: 소프트웨어 환경 표**
*(아래 표를 복사하여 `experiment_report.md` 파일에 사용)*

| 항목 (Item)                  | 버전 (Version)       |
| :--------------------------- | :------------------- |
| **운영체제 (OS)**              | `Ubuntu 20.04.5 LTS` |
| **Python 버전**              | `3.9.12`             |
| **CUDA 버전**                | `11.7`               |
| **NVIDIA 드라이버**            | `515.86.01`          |
| **주요 라이브러리 (Key Libs)** |                      |
| `torch`                      | `1.13.1+cu117`       |
| `torchaudio`                 | `0.13.1+cu117`       |
| `transformers`               | `4.25.1`             |

---

## 5. Git 워크플로우 (Git Workflow)

### 5.1. 브랜치 규칙 (Branching Strategy)

- **`main`**: 배포 또는 최종 결과물 수준의 코드만 존재. (직접 Push 금지)
- **`develop`**: 개발의 중심이 되는 브랜치. 모든 기능 브랜치의 통합 지점
- **`feature/{도메인}/{기능명}`**: 새로운 기능 개발, 실험 등을 위한 브랜치
  - **도메인 (Domain) 정의 예시**:
    - `model-vttt`: 배니싱 틱택토 AI 모델 개발
    - `display-control`: 디스플레이 제어
    - `game-logic`: 게임 규칙 및 상태 관리
  - **예시**:
    - `feature/model-vttt/dqn-training`
    - `feature/display-control/led-grid-sync`
    - `feature/game-logic/vanishing-rule`
      
- **`fix/{도메인}/{수정내용}`**: 특정 도메인의 버그를 수정하기 위한 브랜치
  - **예시**: `fix/display-control/side-move-bug`
- **`docs/{문서명}`**: README 등 문서 작업을 위한 브랜치

### 5.2. 개발 프로세스

1.  **Issue 생성**: 새로운 기능, 실험, 버그 수정이 필요할 경우 GitHub Issue를 생성
2.  **Branch 생성**: `develop` 브랜치에서 자신의 도메인에 맞는 `feature` 브랜치를 생성
    ```bash
    # 예시: A가 디스플레이에서의 말 움직임 로직을 추가할 경우
    git checkout develop
    git pull origin develop
    git checkout -b feature/display-control/board-movement-logic
    ```
3.  **작업 및 Commit**: 해당 브랜치에서 자유롭게 작업하고 커밋합니다. (커밋 메시지 규칙 준수)
4.  **Push**: 작업이 완료되면 원격 저장소에 Push 
    ```bash
    git push origin feature/text-emotion/add-new-model
    ```
5.  **Pull Request (PR) 생성**:
    - `feature/{도메인}/{기능명}` 브랜치를 `develop` 브랜치로 향하는 PR을 생성
    - PR 템플릿에 따라 변경 사항, 실험 결과(성능 지표 포함), 리뷰 요청 사항을 상세히 기재
6.  **코드 리뷰**: 최소 1명 이상의 동료 연구원에게 코드 리뷰를 받습니다. 리뷰 의견을 반영하여 코드를 수정
7.  **Merge**: 리뷰 승인(Approve) 후, PR을 `develop` 브랜치에 Merge  (`Squash and Merge` 권장)
8.  **브랜치 삭제**: Merge가 완료된 `feature` 브랜치는 삭제

## 6. 모델 실행 관련

### 6.1 의존성 설치
```
~ % pip install -r requirements.txt
```  

### 6.2 모델 실행
```
~ % python vanishing_tictactoe_rl_full.py play \
  --checkpoint ./vanish_runs/checkpoints/best.pt \
  --human_first \
  --search_depth 6
```
