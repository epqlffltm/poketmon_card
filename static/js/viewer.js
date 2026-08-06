// static/js/viewer.js
//
// 카드 이미지 확대 보기.
//
// 직접 오버레이를 구현하는 대신 <dialog> 의 showModal() 을 사용한다.
// 배경 딤 처리, ESC 키 닫기, 포커스 가두기, 접근성 속성이 모두 기본 제공되므로
// 배경 클릭 처리와 고해상도 이미지 교체만 직접 다루면 된다.
//
// pokemontcg.io 는 파일명 뒤에 _hires 를 붙인 고해상도 이미지를 함께 제공한다.
// 목록에는 작은 이미지를, 확대 시에는 고해상도를 사용한다.

const ImageViewer = (() => {
  let dialog, image, caption, closeBtn;

  /** https://.../base1/58.png -> https://.../base1/58_hires.png */
  function toHiRes(url) {
    if (!url) return "";
    return url.replace(/(\.[a-z]+)(\?.*)?$/i, "_hires$1$2");
  }

  function open(smallUrl, altText, captionText) {
    if (!smallUrl) return;

    // 고해상도는 용량이 커서 즉시 뜨지 않는다.
    // 우선 작은 이미지를 보여주고 로딩이 끝나면 교체한다.
    image.src = smallUrl;
    image.alt = altText || "";
    image.classList.add("viewer__image--loading");
    caption.textContent = captionText || "";

    const hires = new Image();
    hires.onload = () => {
      image.src = hires.src;
      image.classList.remove("viewer__image--loading");
    };
    // 고해상도가 없는 카드도 있으므로 실패해도 작은 이미지를 유지한다
    hires.onerror = () => image.classList.remove("viewer__image--loading");
    hires.src = toHiRes(smallUrl);

    dialog.showModal();
  }

  function init() {
    dialog = document.getElementById("viewer");
    image = document.getElementById("viewer-image");
    caption = document.getElementById("viewer-caption");
    closeBtn = document.getElementById("viewer-close");

    closeBtn.addEventListener("click", () => dialog.close());

    // 배경 클릭으로 닫기.
    // dialog 자체가 화면 전체를 차지하므로 클릭 좌표가 내용 영역 밖인지 직접 판정한다.
    dialog.addEventListener("click", (event) => {
      const box = image.getBoundingClientRect();
      const outside =
        event.clientX < box.left ||
        event.clientX > box.right ||
        event.clientY < box.top ||
        event.clientY > box.bottom;
      if (outside) dialog.close();
    });

    // 닫힌 뒤 이미지를 비워 다음에 열 때 이전 카드가 잠깐 보이지 않게 한다
    dialog.addEventListener("close", () => {
      image.removeAttribute("src");
    });
  }

  return { init, open };
})();