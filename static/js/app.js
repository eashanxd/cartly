document.addEventListener("DOMContentLoaded", () => {
  const menuToggle = document.querySelector(".menu-toggle");
  const navLinks = document.querySelector("#primary-links");

  if (menuToggle && navLinks) {
    const closeNavigation = () => {
      menuToggle.setAttribute("aria-expanded", "false");
      menuToggle.setAttribute("aria-label", "Open navigation");
      navLinks.classList.remove("is-open");
    };

    menuToggle.addEventListener("click", () => {
      const expanded = menuToggle.getAttribute("aria-expanded") === "true";
      menuToggle.setAttribute("aria-expanded", String(!expanded));
      menuToggle.setAttribute("aria-label", expanded ? "Open navigation" : "Close navigation");
      navLinks.classList.toggle("is-open", !expanded);
    });

    navLinks.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", closeNavigation);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && menuToggle.getAttribute("aria-expanded") === "true") {
        closeNavigation();
        menuToggle.focus();
      }
    });
  }

  document.querySelectorAll("[data-auto-submit]").forEach((select) => {
    select.addEventListener("change", () => select.form?.requestSubmit());
  });

  document.querySelectorAll("[data-toast]").forEach((toast) => {
    const dismiss = () => {
      toast.classList.add("toast-hiding");
      window.setTimeout(() => toast.remove(), 220);
    };
    toast.querySelector(".toast-close")?.addEventListener("click", dismiss);
    window.setTimeout(dismiss, 4500);
  });

  document.querySelectorAll("[data-fallback-image]").forEach((image) => {
    image.addEventListener("error", () => {
      image.src = "/static/img/product-placeholder.svg";
      image.removeAttribute("data-fallback-image");
    }, { once: true });
    if (!image.getAttribute("src")) {
      image.src = "/static/img/product-placeholder.svg";
    }
  });

  const mainProductImage = document.querySelector(".detail-image > img");
  document.querySelectorAll("[data-product-image]").forEach((button) => {
    button.addEventListener("click", () => {
      if (mainProductImage) mainProductImage.src = button.dataset.productImage;
    });
  });

  document.querySelectorAll("[data-quantity-control]").forEach((control) => {
    const input = control.querySelector('input[type="number"]');
    if (!input) return;

    control.querySelectorAll("[data-quantity-step]").forEach((button) => {
      button.addEventListener("click", () => {
        const step = Number(button.dataset.quantityStep);
        const min = Number(input.min) || 1;
        const max = Number(input.max) || Number.MAX_SAFE_INTEGER;
        const current = Number(input.value) || min;
        input.value = String(Math.min(max, Math.max(min, current + step)));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
  });

  document.querySelectorAll("[data-checkout]").forEach((button) => {
    button.addEventListener("click", () => {
      const message = document.querySelector("[data-checkout-message]");
      if (message) message.hidden = false;
    });
  });
});
