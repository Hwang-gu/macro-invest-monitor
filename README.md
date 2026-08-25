# 매크로 배분 연구 파이프라인

2000-01-01부터의 **코스피·코스닥·나스닥·S&P500, 미국/한국 장단기 금리, 원/달러, CPI, 금, 비트코인**을 모으고, 전쟁·질병·신기술 이슈와 함께 상관·파급경로를 본 뒤, **금 / 비트코인 / 주식** 중 어디에 비중을 둘지, 주식이면 **코스피·코스닥·나스닥**, 그다음 **바이오·반도체·금융·로봇·조선** 점수를 매일 갱신합니다.

연구용이며 **투자 권유가 아닙니다.**

## 가설을 데이터로 검증하는 방식

예를 들어 “미국 단기금리가 내려가면 원/달러가 내리고, 수입물가가 안정되지만 수출 기업 실적은 나빠질 수 있다”는 경로는 코드에 **가정으로 박아 두지 않습니다.** 월간 변화의 동월 상관과 시차 상관으로 세기를 재고, 그 위에 국면 규칙(완화/원화강세/장단기역전/이슈)을 더해 점수를 조정합니다.

## 데이터

| 항목 | 소스 | 비고 |
|---|---|---|
| 코스피, 코스닥, 나스닥, S&P500, 금선물, BTC, 원/달러, VIX | Yahoo Finance | BTC는 2014-09 이후 |
| 미국 3개월·2년·10년, CPI, 연준금리 | FRED CSV | API 키 불필요 |
| 한국 기준금리·장기국채·CPI | FRED 월간 / ECOS 일별 | `.env`의 `BOK_API_KEY`가 있으면 한은 기준금리 일별. 없으면 FRED(OECD) 월간 기준금리. CPI는 2023-11 이후 끊기면 World Bank 연간 인플레로 보완. |
| 업종 | 미국 ETF + 한국 대표주 | 아래 대용 목록 |

업종 대용: 미국 반도체 SMH, 바이오 IBB, 금융 XLF, 로봇 BOTZ(2016-). 한국 반도체 SK하이닉스, 바이오 셀트리온, 금융 신한지주, 조선 HD한국조선해양, 로봇/자동화 LS일렉트릭.

이슈는 [`data/events.json`](data/events.json)에서 직접 고치면 다음 실행에 반영됩니다.

## 설치

Python 3.11+ (3.14 확인됨).

```powershell
cd C:\Users\조현성\Desktop\Model\model
python -m pip install -r requirements.txt
copy .env.example .env
```

선택:

- `GEMINI_API_KEY` — [Google AI Studio](https://aistudio.google.com/apikey). Cursor Pro / Gemini 웹 구독과 별개입니다. 없으면 규칙 기반 한국어 해설만 씁니다.
- `BOK_API_KEY` — [한국은행 ECOS](https://ecos.bok.or.kr/api/) 인증키. 있으면 한국 기준금리 일별, 없으면 FRED 월간 기준금리.

## 사용

처음 한 번 (2000년부터 전체 수집, 수 분 소요):

```powershell
python -m src --mode history
```

매일 증분:

```powershell
python -m src --mode daily
```

대시보드:

```powershell
streamlit run app/dashboard.py
```

## 휴대폰에서 보기 (PC가 꺼져 있어도 매일 갱신)

이 컴퓨터가 꺼져 있으면 Windows 스케줄러는 돌지 않습니다. 대신 GitHub Actions가 **매일 07:00(한국시간)** 에 시세를 받고, 모바일 웹앱을 배포합니다.

아이폰: Safari로 연 뒤 공유 → **홈 화면에 추가**  
안드로이드: 크롬 메뉴 → **홈 화면에 추가**

배포 주소는 저장소를 GitHub에 올린 뒤 `https://<계정>.github.io/<저장소>/` 입니다. 페이지는 **공개 URL**이라 링크가 있는 사람은 볼 수 있습니다.

한은 인증키는 GitHub Secrets의 `BOK_API_KEY`로 넣습니다. `.env`는 올리지 않습니다.


## 모형이 하는 일 / 하지 않는 일

- **하는 일:** 금리·환율·물가·모멘텀·이슈 더미로 향후 21거래일 수익률을 Ridge로 적합하고, 국면 규칙을 더해 **상대 순위**를 만듭니다.
- **하지 않는 일:** 내일 종가 맞히기, 레버리지·개별 종목 타이밍. 후반 표본 R²는 낮거나 음수일 수 있습니다. 그건 버그가 아니라 금융 예측의 한계입니다.

## 엑셀 장부와 메일

매일 `python -m src --mode daily` 를 돌리면 Cursor를 켜지 않아도 아래가 갱신됩니다.

- [`data/workbook/macro_ledger.xlsx`](data/workbook/macro_ledger.xlsx)
  - **Daily Data** — 2000-01-01부터 달력 매일. 코스피·코스닥·나스닥·S&P500·비트코인·금·미국 장단기 국채·미국 기준금리·한국 기준금리. 주말·휴장은 전일 값.
  - **Issue** — 전쟁·금융위기·코로나 유동성 등 이슈 시계열
  - **Graph** — 월말 지수·금리 차트 + 이슈 여부 막대
  - **Forecast Model** — 금/비트코인/주식 → 코스피·코스닥·나스닥 → 업종 → 코스피 대표 종목
- `data/reports/daily_brief.html` — 이슈 음영이 입혀진 그래프와 근거. 브라우저로 열면 됩니다.
- `streamlit run app/dashboard.py` — 같은 그래프를 대화형으로 봅니다.

`.env`에 SMTP와 `MAIL_TO`를 넣으면 엑셀+HTML을 메일로 보냅니다. Gmail은 **앱 비밀번호**가 필요합니다.

## 폴더

- `data/raw` — 시리즈별 CSV
- `data/processed` — 정렬된 패널, 상관, 이벤트 스터디
- `data/models` — 학습 가중치
- `data/reports/latest.json` — 오늘 추천
- `data/workbook/macro_ledger.xlsx` — 사람이 보는 누적 엑셀
