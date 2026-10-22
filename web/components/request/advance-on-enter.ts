/**
 * Enter in a single-line field moves to the next field instead of sending the form (the phone's
 * keyboard labels that key "Avanti"; sending a half-written request there throws an error wall at
 * the person typing). Enter sends the form only from the last single-line field, the budget, whose
 * key reads "Vai" (enterKeyHint="go"). A text area keeps its new line, a button its click, a
 * select its own keys.
 */

import type { KeyboardEvent } from "react";

/** The fields in the order the form shows them: inputs, selects and text areas that can take focus.
 * Buttons are not stops, and neither are the radios of a segmented choice that already has its
 * answer (the one Enter was pressed on excepted): Enter goes on to the field the choice opens. The
 * chosen radio of a group marked `data-enter-stop` (the travel mode, whose default decides what
 * the agents research) is a stop, so Enter never passes that choice unseen. */
function stops(form: HTMLFormElement, from: EventTarget | null): HTMLElement[] {
  return Array.from(form.elements).filter((element): element is HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement => {
    if (element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement) return !element.disabled;
    if (!(element instanceof HTMLInputElement) || element.disabled) return false;
    if (["button", "submit", "reset", "image", "hidden"].includes(element.type)) return false;
    if (element.type !== "radio" || element === from) return true;
    return element.checked && element.closest("[data-enter-stop]") !== null;
  });
}

/** The field Enter should move to from `target`; null when Enter should send the form (no
 * single-line field follows) or the key is not Enter's business. */
export function nextFieldAfter(form: HTMLFormElement, target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof HTMLInputElement) || ["button", "submit", "reset", "image"].includes(target.type)) return null;
  const list = stops(form, target);
  const index = list.indexOf(target);
  if (index < 0) return null;
  const after = list.slice(index + 1);
  // The last single-line field sends the form.
  if (!after.some((element) => element instanceof HTMLInputElement)) return null;
  return after[0] ?? null;
}

/** `onKeyDown` of the form. */
export function advanceOnEnter(event: KeyboardEvent<HTMLFormElement>): void {
  if (event.key !== "Enter" || event.defaultPrevented || event.nativeEvent.isComposing) return;
  const next = nextFieldAfter(event.currentTarget, event.target);
  if (!next) return;
  event.preventDefault();
  next.focus();
}
