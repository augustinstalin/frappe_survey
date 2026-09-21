/**
 * The handful of browser affordances Vue does not cover.
 *
 * Everything that used to build DOM by hand lives in components now; what is
 * left is genuinely imperative.
 */

/** Grow a textarea to fit its content, so long answers stay readable. */
export function autoGrow(textarea) {
	if (!textarea) return;
	textarea.style.height = "auto";
	textarea.style.height = `${textarea.scrollHeight}px`;
}

export function scrollToTop() {
	window.scrollTo({ top: 0, behavior: "smooth" });
}

export function prefersReducedMotion() {
	return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function isTouchDevice() {
	// Autofocusing on a phone pops the keyboard over the question, which is
	// worse than no autofocus at all.
	return window.matchMedia("(hover: none)").matches;
}

/** Move focus to the first thing on the page somebody can answer with. */
export function focusFirstInput(scope) {
	if (!scope || isTouchDevice()) return;
	const target = scope.querySelector(
		"input:not([type=hidden]):not([disabled]), textarea, select"
	);
	if (target) target.focus();
}

/**
 * Preload a background before swapping it in, so the page never flashes an
 * empty background mid-transition.
 */
export function setBackground(node, url) {
	if (!node || !url) return;
	const image = new Image();
	image.onload = () => node.style.setProperty("--survey-background", `url('${url}')`);
	image.src = url;
}
