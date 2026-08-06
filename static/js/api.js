// static/js/api.js
//
// 백엔드 응답 형태를 아는 유일한 모듈.
// 응답 구조가 바뀌면 여기만 수정하면 되도록 화면 로직과 분리했다.

const API = (() => {
  const BASE = "/api/v1";

  async function request(path) {
    const res = await fetch(`${BASE}${path}`);
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || `요청 실패 (${res.status})`);
    }
    return res.json();
  }

  return {
    listCards() {
      return request("/cards");
    },

    getPrices(cardId, { condition = "NM", period = "30d" } = {}) {
      const query = new URLSearchParams({ condition, period });
      return request(`/cards/${cardId}/prices?${query}`);
    },
  };
})();