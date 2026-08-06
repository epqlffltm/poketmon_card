// static/js/app.js
//
// 화면 조립과 상태 관리.
//
// 표시 규칙 두 가지가 백엔드 설계와 직결된다.
//
//   1. 변동률의 null 은 '변동 없음'이 아니라 '비교 가능한 과거 데이터 없음'이다.
//      0% 와 반드시 구분해 표시한다.
//   2. 변동률의 base_date 가 요청 기간과 어긋날 수 있다.
//      빈 날짜 fallback 때문이며, 실제 비교 시점을 함께 노출한다.

(() => {
  const CONDITIONS = [
    { value: "NM", label: "NM" },
    { value: "LP", label: "LP" },
    { value: "MP", label: "MP" },
    { value: "HP", label: "HP" },
    { value: "DMG", label: "DMG" },
  ];

  const PERIODS = [
    { value: "7d", label: "7일" },
    { value: "30d", label: "30일" },
    { value: "90d", label: "90일" },
  ];

  const CHANGE_LABELS = {
    day_1: { title: "1일", days: 1 },
    day_7: { title: "7일", days: 7 },
    day_30: { title: "30일", days: 30 },
  };

  const state = { cardId: null, condition: "NM", period: "30d" };

  const $ = (id) => document.getElementById(id);
  const won = (v) => `${Math.round(Number(v)).toLocaleString("ko-KR")}원`;

  function daysBetween(a, b) {
    return Math.round((new Date(a) - new Date(b)) / 86_400_000);
  }

  // ---------- 카드 목록 ----------

  function renderCardList(cards) {
    const list = $("card-list");
    list.innerHTML = "";

    cards.forEach((card) => {
      const li = document.createElement("li");
      li.className = "card-item";
      li.dataset.cardId = card.id;
      li.innerHTML = `
        <span class="card-item__dex">#${card.pokedex_number}</span>
        <span class="card-item__name">${card.name_ko}</span>
      `;
      li.addEventListener("click", () => selectCard(card.id));
      list.appendChild(li);
    });
  }

  function highlightCard(cardId) {
    document.querySelectorAll(".card-item").forEach((el) => {
      el.classList.toggle(
        "card-item--active",
        Number(el.dataset.cardId) === cardId
      );
    });
  }

  // ---------- 조회 조건 ----------

  function renderSegmented(container, options, current, onChange) {
    container.innerHTML = "";
    options.forEach((opt) => {
      const btn = document.createElement("button");
      btn.className =
        "segmented__btn" +
        (opt.value === current ? " segmented__btn--active" : "");
      btn.textContent = opt.label;
      btn.addEventListener("click", () => onChange(opt.value));
      container.appendChild(btn);
    });
  }

  // ---------- 시세 ----------

  function renderPrices(current) {
    const grid = $("price-grid");

    if (!current) {
      grid.innerHTML = `<div class="stat"><div class="stat__label">시세</div>
        <div class="stat__value" style="font-size:15px">데이터 없음</div></div>`;
      return;
    }

    // 절단 전후 차이가 크면 이상치가 많았다는 뜻이므로 함께 보여준다.
    const trimmed =
      Number(current.raw_max_price) > Number(current.max_price) * 1.2;

    grid.innerHTML = `
      <div class="stat stat--primary">
        <div class="stat__label">평균가</div>
        <div class="stat__value">${won(current.avg_price)}</div>
        <div class="stat__sub">중앙값 ${won(current.median_price)}</div>
      </div>
      <div class="stat">
        <div class="stat__label">최저가</div>
        <div class="stat__value">${won(current.min_price)}</div>
        ${trimmed ? `<div class="stat__sub">원본 ${won(current.raw_min_price)}</div>` : ""}
      </div>
      <div class="stat">
        <div class="stat__label">최고가</div>
        <div class="stat__value">${won(current.max_price)}</div>
        ${trimmed ? `<div class="stat__sub">원본 ${won(current.raw_max_price)}</div>` : ""}
      </div>
      <div class="stat">
        <div class="stat__label">표본 수</div>
        <div class="stat__value">${current.sample_count}건</div>
        <div class="stat__sub">${current.snapshot_date}</div>
      </div>
    `;
  }

  function renderChanges(rates, latestDate) {
    const grid = $("change-grid");

    grid.innerHTML = Object.entries(CHANGE_LABELS)
      .map(([key, meta]) => {
        const item = rates[key];

        // null 은 0% 가 아니다. 비교할 과거 데이터가 없다는 뜻.
        if (!item) {
          return `
            <div class="change">
              <div class="change__label">${meta.title} 변동</div>
              <div class="change__value change__value--none">비교 데이터 없음</div>
            </div>`;
        }

        const rate = Number(item.rate);
        const cls = rate > 0 ? "up" : rate < 0 ? "down" : "";
        const sign = rate > 0 ? "+" : "";

        // fallback 으로 다른 날짜를 참조했는지 확인
        const actual = latestDate ? daysBetween(latestDate, item.base_date) : null;
        const shifted = actual !== null && actual !== meta.days;

        return `
          <div class="change">
            <div class="change__label">${meta.title} 변동</div>
            <div class="change__value ${cls ? `change__value--${cls}` : ""}">
              ${sign}${rate.toFixed(2)}%
            </div>
            <div class="change__base ${shifted ? "change__base--shifted" : ""}">
              ${item.base_date} 대비${shifted ? ` (실제 ${actual}일 전)` : ""}
            </div>
          </div>`;
      })
      .join("");
  }

  function renderChartNote(history) {
    const note = $("chart-note");
    if (!history.length) {
      note.textContent = "";
      return;
    }
    const thin = history.filter((p) => p.sample_count < 8).length;
    const parts = [`스냅샷 ${history.length}건`];
    if (thin) {
      parts.push(`이 중 ${thin}건은 표본 8건 미만으로 이상치 절단을 적용하지 않았습니다`);
    }
    note.textContent = parts.join(" · ");
  }

  // ---------- 조회 ----------

  async function load() {
    if (!state.cardId) return;

    const data = await API.getPrices(state.cardId, {
      condition: state.condition,
      period: state.period,
    });

    $("card-image").src = data.card.image_url || "";
    $("card-image").alt = data.card.name_ko;
    $("card-name").textContent = data.card.name_ko;
    $("card-meta").textContent =
      `${data.card.name_en} · ${data.card.set_code} #${data.card.card_number}` +
      (data.card.rarity ? ` · ${data.card.rarity}` : "");

    renderPrices(data.current);
    renderChanges(data.change_rates, data.current?.snapshot_date);
    renderChartNote(data.history);
    PriceChart.render($("price-chart"), data.history);
  }

  function selectCard(cardId) {
    state.cardId = cardId;
    highlightCard(cardId);
    $("empty-state").hidden = true;
    $("content").hidden = false;
    load();
  }

  // ---------- 초기화 ----------

  function bindControls() {
    renderSegmented($("condition-select"), CONDITIONS, state.condition, (v) => {
      state.condition = v;
      bindControls();
      load();
    });
    renderSegmented($("period-select"), PERIODS, state.period, (v) => {
      state.period = v;
      bindControls();
      load();
    });
  }

  async function init() {
    bindControls();

    try {
      const cards = await API.listCards();
      renderCardList(cards);
      if (cards.length) selectCard(cards[0].id);
    } catch (err) {
      $("card-list").innerHTML =
        `<li class="card-list__empty">불러오기 실패: ${err.message}</li>`;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();