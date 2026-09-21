/**
 * Entry point for the public survey page.
 *
 * Boots from the payload the server already rendered into the page, so the
 * first screen needs no round trip.
 *
 * Vue comes from Frappe's own node_modules: esbuild's `nodePaths` includes
 * every installed app's, so `import ... from "vue"` resolves without this app
 * carrying a dependency of its own.
 */

import { createApp } from "vue";

import App from "./player/App.vue";

function readBootstrap() {
	const script = document.querySelector("[data-survey-bootstrap]");
	if (!script) return { state: "error", message: "This survey could not be loaded." };

	try {
		return JSON.parse(script.textContent);
	} catch (error) {
		console.error("survey: could not parse bootstrap payload", error);
		return { state: "error", message: "This survey could not be loaded." };
	}
}

function boot() {
	const mount = document.querySelector("[data-survey-app]");
	if (!mount) return;

	const app = createApp(App, {
		surveyToken: mount.dataset.surveyToken || "",
		bootstrap: readBootstrap(),
	});

	// Anything the player itself cannot recover from should still leave a
	// readable page rather than a blank one.
	app.config.errorHandler = (error) => console.error("survey player:", error);

	app.mount(mount);
}

if (document.readyState === "loading") {
	document.addEventListener("DOMContentLoaded", boot);
} else {
	boot();
}
