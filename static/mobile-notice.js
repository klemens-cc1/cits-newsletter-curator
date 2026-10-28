// Phone visitors: once per visit, suggest using a computer. Delphi's layouts are desktop-only.
(function () {
  if (!window.matchMedia("(pointer: coarse) and (max-width: 768px)").matches) return;
  try {
    if (sessionStorage.getItem("mobileNoticeSeen")) return;
    sessionStorage.setItem("mobileNoticeSeen", "1");
  } catch (e) { /* storage blocked: still show it */ }

  const overlay = document.createElement("div");
  overlay.style.cssText =
    "position:fixed;inset:0;z-index:1000;background:rgba(37,37,37,0.6);" +
    "display:flex;align-items:center;justify-content:center;padding:16px;";

  const box = document.createElement("div");
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  box.setAttribute("aria-labelledby", "mobileNoticeTitle");
  box.style.cssText =
    "background:#fff;border-top:3px solid #ba0c2f;max-width:340px;padding:24px;" +
    "box-shadow:0 8px 32px rgba(0,0,0,0.35);";

  const title = document.createElement("h2");
  title.id = "mobileNoticeTitle";
  title.textContent = "Best on a computer";
  title.style.cssText =
    "font-family:'Oswald',sans-serif;font-weight:500;font-size:20px;color:#252525;margin:0 0 10px;";

  const body = document.createElement("p");
  body.textContent =
    "Delphi is built for a laptop or desktop screen. On a phone, some pages and buttons may not fit or work properly.";
  body.style.cssText =
    "font-family:'Merriweather',serif;font-size:14px;line-height:1.6;color:#555;margin:0 0 20px;";

  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Continue anyway";
  button.style.cssText =
    "font-family:'Oswald',sans-serif;font-size:13px;letter-spacing:1px;text-transform:uppercase;" +
    "background:#ba0c2f;color:#fff;border:0;padding:12px 18px;width:100%;cursor:pointer;";

  const close = () => overlay.remove();
  button.addEventListener("click", close);
  document.addEventListener("keydown", function onKey(e) {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", onKey); }
  });

  box.append(title, body, button);
  overlay.append(box);
  document.body.append(overlay);

  // Pages wider than the phone stretch the layout viewport, so centring in the overlay
  // can land off-screen; place the box in the visible area instead.
  const vv = window.visualViewport;
  if (vv) {
    const width = Math.min(340, vv.width - 32);
    box.style.position = "fixed";
    box.style.width = width + "px";
    box.style.left = vv.offsetLeft + (vv.width - width) / 2 + "px";
    box.style.top = vv.offsetTop + Math.max(16, (vv.height - box.offsetHeight) / 2) + "px";
  }
  button.focus();
})();
