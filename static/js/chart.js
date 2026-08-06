// static/js/chart.js
//
// Chart.js 래핑.
//
// 평균가는 선으로, 최소~최대 구간은 밴드로 그린다.
// 밴드는 Chart.js 에 전용 기능이 없으므로 최소가 데이터셋을 투명하게 두고
// 최대가 데이터셋이 그 지점까지 채우도록(fill: '-1') 구성한다.
//
// 표본이 부족한 날은 백엔드가 이상치 절단을 건너뛰므로 min/max 에 극단값이 남는다.
// 그대로 그리면 y축이 스파이크에 끌려가 정작 중요한 가격대가 납작하게 눌린다.
// 해당 지점의 밴드를 null 로 끊어 구간을 그리지 않고, 평균선에는 점을 찍어
// '이 날은 표본이 부족하다'를 시각적으로 드러낸다.

const PriceChart = (() => {
  // 백엔드 settings.min_samples_for_trimming 과 같은 값이어야 한다.
  const MIN_SAMPLES = 8;

  const ACCENT = "#ffcb05";
  const GRID = "rgba(255, 255, 255, 0.06)";
  const TICK = "#646c7a";

  let instance = null;

  const won = (v) => `${Math.round(v).toLocaleString("ko-KR")}원`;

  // '2026-08-06' -> '8/6'
  const shortDate = (iso) => {
    const [, m, d] = iso.split("-");
    return `${Number(m)}/${Number(d)}`;
  };

  function render(canvas, history) {
    if (instance) instance.destroy();

    const labels = history.map((p) => shortDate(p.snapshot_date));
    const reliable = history.map((p) => p.sample_count >= MIN_SAMPLES);

    // 표본이 부족한 날은 밴드를 그리지 않는다
    const band = (key) =>
      history.map((p, i) => (reliable[i] ? Number(p[key]) : null));

    instance = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "최소가",
            data: band("min_price"),
            borderColor: "transparent",
            pointRadius: 0,
            fill: false,
          },
          {
            label: "최대가",
            data: band("max_price"),
            borderColor: "transparent",
            backgroundColor: "rgba(255, 203, 5, 0.13)",
            pointRadius: 0,
            // '-1' 은 바로 이전 데이터셋(최소가)까지 채우라는 뜻
            fill: "-1",
          },
          {
            label: "평균가",
            data: history.map((p) => Number(p.avg_price)),
            borderColor: ACCENT,
            borderWidth: 2,
            // 표본 부족한 날만 점을 찍어 신뢰도가 낮음을 표시한다
            pointRadius: (ctx) => (reliable[ctx.dataIndex] ? 0 : 3),
            pointBackgroundColor: "#0f1115",
            pointBorderColor: ACCENT,
            pointBorderWidth: 1.5,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: ACCENT,
            tension: 0.25,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#1e222b",
            borderColor: "#2a2f3a",
            borderWidth: 1,
            titleColor: "#e6e8ec",
            bodyColor: "#9099a8",
            padding: 10,
            displayColors: false,
            callbacks: {
              title: (items) => history[items[0].dataIndex].snapshot_date,
              label: (item) =>
                item.parsed.y === null
                  ? null
                  : `${item.dataset.label}  ${won(item.parsed.y)}`,
              afterBody: (items) => {
                const point = history[items[0].dataIndex];
                const lines = [`표본 ${point.sample_count}건`];
                if (point.sample_count < MIN_SAMPLES) {
                  lines.push("표본 부족 · 이상치 절단 미적용");
                }
                return lines;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: GRID, drawTicks: false },
            ticks: { color: TICK, maxRotation: 0, autoSkipPadding: 20 },
            border: { display: false },
          },
          y: {
            grid: { color: GRID, drawTicks: false },
            ticks: {
              color: TICK,
              callback: (v) => `${Math.round(v / 1000)}k`,
            },
            border: { display: false },
          },
        },
      },
    });
  }

  return { render };
})();