// The brain routes the renderer may call through main (brainRequest). Never auth, never another
// host; the token stays in main. `src/renderer/brainRoutes.test.ts` checks every route the UI uses.
export const BRAIN_METHODS = new Set(["GET", "POST", "PATCH", "DELETE"]);
export const BRAIN_PATH =
  /^\/v2\/(?:jobs|incidents|capabilities\/tools|permissions\/rules|devices|settings|engines\/chains|threads|artifacts|memories)(?:\/[\w-]+){0,3}(?:\?[\w=&%.'!*()~-]{0,200})?$/;
