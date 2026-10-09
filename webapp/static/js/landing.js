document.addEventListener("DOMContentLoaded", () => {
  const code = document.querySelector(".hero-code");
  if (!code) return;

  const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
  const segments = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    segments.push({ node, text: node.textContent || "" });
    node.textContent = "";
  }

  const cursor = document.createElement("span");
  cursor.className = "typing-cursor";
  cursor.setAttribute("aria-hidden", "true");
  code.append(cursor);

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    segments.forEach(({ node, text }) => {
      node.textContent = text;
    });
    cursor.remove();
    return;
  }

  let segmentIndex = 0;
  let characterIndex = 0;

  function typeNextCharacter() {
    while (
      segmentIndex < segments.length &&
      characterIndex >= segments[segmentIndex].text.length
    ) {
      segmentIndex += 1;
      characterIndex = 0;
    }

    if (segmentIndex >= segments.length) {
      cursor.remove();
      return;
    }

    const segment = segments[segmentIndex];
    segment.node.textContent += segment.text[characterIndex];
    characterIndex += 1;
    window.setTimeout(typeNextCharacter, 18);
  }

  typeNextCharacter();
});
