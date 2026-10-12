import { ICON_PATHS, type IconName } from "./icons";
import { ICON_SYMBOL_PREFIX } from "./icon";

/**
 * The icon sprite: one hidden <svg> of <symbol>s, rendered once by the root layout. Icons are
 * Phosphor Icons 2.1.1, weight bold, MIT (provenance in ./icons.ts). A Server Component kept
 * apart from ./icon.tsx, so the path data travels as HTML once per page and never lands in a
 * client bundle that only needs <Icon>.
 */
export function IconSprite() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" style={{ display: "none" }}>
      {(Object.keys(ICON_PATHS) as IconName[]).map((name) => (
        <symbol key={name} id={`${ICON_SYMBOL_PREFIX}${name}`} viewBox="0 0 256 256">
          <path d={ICON_PATHS[name]} />
        </symbol>
      ))}
    </svg>
  );
}
