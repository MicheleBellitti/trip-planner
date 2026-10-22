import { useId, type ComponentProps, type ComponentPropsWithoutRef, type ReactNode } from "react";

import { cx } from "./cx";
import { Icon, type IconName } from "./icon";

/** What a Field hands to its control: wire them onto the input as they are. */
export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
  required?: boolean;
}

interface FieldProps {
  /** The label, above the control, sentence case ("Da dove parti"). */
  label: ReactNode;
  /** Help under the label, ink-2 ("Una città o un aeroporto"). */
  hint?: ReactNode;
  /** What is wrong and how to fix it, under the control, in error red with a cross. */
  error?: ReactNode;
  /** Marks the label "(facoltativo)". Required fields carry no mark: most of the form is. */
  optional?: boolean;
  /** Use the given id instead of a generated one (e.g. to target it from a summary link). */
  id?: string;
  children: (control: FieldControlProps) => ReactNode;
  className?: string;
}

/**
 * A labelled form control: label above, hint, the control, the error below (never a placeholder
 * as label). It generates the ids and passes them to the control through `children`, so the
 * label, the hint and the error are always announced with it.
 */
export function Field({ label, hint, error, optional = false, id, children, className }: FieldProps) {
  const generated = useId();
  const controlId = id ?? generated;
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cx("grid gap-1.5", className)}>
      <label htmlFor={controlId} className="text-meta font-semibold text-ink">
        {label}
        {optional ? <span className="font-normal text-ink-2"> (facoltativo)</span> : null}
      </label>
      {hint ? (
        <p id={hintId} className="-mt-1 text-meta text-ink-2">
          {hint}
        </p>
      ) : null}
      {children({
        id: controlId,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
        required: optional ? undefined : true,
      })}
      {error ? (
        <p id={errorId} className="flex items-start gap-1.5 text-meta text-error">
          <Icon name="x-circle" size={15} className="mt-0.5" />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}

/** Inputs use the 16 px `input` step so iOS Safari does not zoom on focus. */
const CONTROL =
  "rounded-sm border-[1.5px] border-rule-strong bg-surface text-input text-ink " +
  "placeholder:text-ink-2 transition-[border-color] duration-(--duration-hover) ease-out " +
  "not-disabled:hover:border-ink focus-visible:border-ink aria-invalid:border-error " +
  "disabled:cursor-not-allowed disabled:opacity-55";

/** `ref` is an ordinary prop (React 19): a form that moves focus onto the field after an error passes it. */
export function TextInput({ className, type = "text", ...props }: ComponentProps<"input">) {
  return <input type={type} className={cx(CONTROL, "min-h-11 w-full px-3", className)} {...props} />;
}

/** Two rows get a two-line box (64 px); three or more the usual 96 px. `ref` is an ordinary prop. */
export function TextArea({ className, rows = 3, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      rows={rows}
      className={cx(CONTROL, rows <= 2 ? "min-h-16" : "min-h-24", "w-full resize-y px-3 py-2.5", className)}
      {...props}
    />
  );
}

/** A native select (the phone's own picker), with the caret drawn from the icon sprite. */
export function Select({ className, children, ...props }: ComponentPropsWithoutRef<"select">) {
  return (
    <span className={cx("relative block", className)}>
      <select className={cx(CONTROL, "min-h-11 w-full appearance-none pr-10 pl-3")} {...props}>
        {children}
      </select>
      <Icon
        name="caret-down"
        size={16}
        className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-ink-2"
      />
    </span>
  );
}

interface NumberStepperProps extends Omit<ComponentPropsWithoutRef<"input">, "type" | "value" | "onChange"> {
  value: number;
  onValueChange: (value: number) => void;
  min?: number;
  max?: number;
  /** Names the buttons: "Togli un adulto" / "Aggiungi un adulto". */
  decrementLabel: string;
  incrementLabel: string;
}

/** A count with − and + (adults, children): a real number input in the middle, so it types,
 * reads as a spinbutton and keeps the arrow keys. */
export function NumberStepper({
  value,
  onValueChange,
  min = 0,
  max = 99,
  decrementLabel,
  incrementLabel,
  className,
  disabled,
  ...props
}: NumberStepperProps) {
  const clamp = (next: number) => Math.min(max, Math.max(min, next));
  const step =
    "grid size-11 shrink-0 place-items-center rounded-full border-[1.5px] border-rule-strong text-ink " +
    "transition-[background-color] duration-(--duration-hover) not-disabled:hover:bg-notice-wash " +
    "disabled:cursor-not-allowed disabled:opacity-55";
  return (
    <span className={cx("inline-flex items-center gap-2", className)}>
      <button
        type="button"
        className={step}
        aria-label={decrementLabel}
        disabled={disabled || value <= min}
        onClick={() => onValueChange(clamp(value - 1))}
      >
        <Icon name="minus" size={16} />
      </button>
      <input
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(event) => {
          const next = Number.parseInt(event.target.value, 10);
          if (!Number.isNaN(next)) onValueChange(clamp(next));
        }}
        className={cx(
          CONTROL,
          "min-h-11 w-14 px-1 text-center font-semibold [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
        )}
        {...props}
      />
      <button
        type="button"
        className={step}
        aria-label={incrementLabel}
        disabled={disabled || value >= max}
        onClick={() => onValueChange(clamp(value + 1))}
      >
        <Icon name="plus" size={16} />
      </button>
    </span>
  );
}

interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

interface SegmentedControlProps<T extends string> {
  /** The question, as the group's legend ("Dove vai"). */
  legend: ReactNode;
  /** Keep the legend for screen readers only, when a heading right above already says it
   * ("Quando" over "Date fisse" / "Mese e notti"). */
  legendHidden?: boolean;
  name: string;
  options: readonly SegmentedOption<T>[];
  value: T;
  onValueChange: (value: T) => void;
  className?: string;
}

/** Two or three mutually exclusive choices ("Destinazione" / "Suggeriscimi tu", "Date fisse" /
 * "Un mese"): native radios in a fieldset, drawn as one pill track. The chosen segment is ink. */
export function SegmentedControl<T extends string>({
  legend,
  legendHidden = false,
  name,
  options,
  value,
  onValueChange,
  className,
}: SegmentedControlProps<T>) {
  return (
    <fieldset className={cx("grid min-w-0 gap-1.5 border-0 p-0", className)}>
      <legend className={legendHidden ? "sr-only" : "mb-1.5 p-0 text-meta font-semibold text-ink"}>{legend}</legend>
      <div className="flex rounded-full border-[1.5px] border-rule-strong bg-surface p-[3px]">
        {options.map((option) => (
          <label
            key={option.value}
            className={cx(
              // 40 px labels on the phone with the track's padding added to the tap area (46 px, no dead
              // ring); 36 px from 640 px.
              "relative flex min-h-10 flex-1 cursor-pointer items-center justify-center rounded-full px-3 text-small font-semibold text-ink sm:min-h-9",
              "before:absolute before:-inset-[3px] before:rounded-full",
              "transition-[background-color,color] duration-(--duration-hover) ease-out hover:bg-notice-wash",
              "has-checked:bg-action has-checked:text-on-action has-checked:hover:bg-action",
              "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-focus",
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onValueChange(option.value)}
              className="sr-only"
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export interface ChoiceChipOption<T extends string> {
  value: T;
  label: string;
  icon: IconName;
}

interface ChoiceChipsProps<T extends string> {
  /** The question, as the group's legend ("Come viaggi"). */
  legend: ReactNode;
  /** Help under the legend, ink-2: the group's description, heard once on entering it. */
  hint?: ReactNode;
  /** A line under the chips about the chosen option ("A bordo a piedi: …"), or nothing. It sits in
   * a polite live region that is always there, so the line a choice brings is announced. */
  note?: ReactNode;
  /** What is wrong, under the chips, in error red with a cross (as Field draws it). */
  error?: ReactNode;
  name: string;
  options: readonly ChoiceChipOption<T>[];
  value: T;
  onValueChange: (value: T) => void;
  /** Set on the chosen radio: where a form moves the focus for this field's error. */
  id?: string;
  className?: string;
}

/** Four or more mutually exclusive choices, each with an icon (the travel mode): native radios in
 * a fieldset, drawn as pills that wrap onto a second row on the phone. The chosen pill is ink, as
 * the chosen segment of a SegmentedControl; arrow keys move the choice, as in any radio group. */
export function ChoiceChips<T extends string>({
  legend,
  hint,
  note,
  error,
  name,
  options,
  value,
  onValueChange,
  id,
  className,
}: ChoiceChipsProps<T>) {
  const generated = useId();
  const hintId = `${generated}-hint`;
  const noteId = `${generated}-note`;
  const errorId = `${generated}-error`;
  // The group is described by its hint and, while there is one, the note: heard on entering it.
  const describedBy = [hint ? hintId : null, note ? noteId : null].filter(Boolean).join(" ") || undefined;

  return (
    <fieldset
      aria-describedby={describedBy}
      // Enter in a form stops on the chosen chip (components/request/advance-on-enter.ts).
      data-enter-stop=""
      className={cx("grid min-w-0 gap-1.5 border-0 p-0", className)}
    >
      <legend className="mb-1.5 p-0 text-meta font-semibold text-ink">{legend}</legend>
      {hint ? (
        <p id={hintId} className="-mt-1 text-meta text-ink-2">
          {hint}
        </p>
      ) : null}
      <div>
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <label
            key={option.value}
            className={cx(
              // 40 px pills on the phone with 3 px of tap area around them (46 px; the gaps stay
              // 2 px apart); 36 px from 640 px.
              "relative inline-flex min-h-10 cursor-pointer items-center gap-1.5 rounded-full border-[1.5px] border-rule-strong bg-surface px-3.5 text-small font-semibold text-ink sm:min-h-9",
              "before:absolute before:-inset-[3px] before:rounded-full",
              "transition-[background-color,border-color,color] duration-(--duration-hover) ease-out hover:bg-notice-wash",
              "has-checked:border-action has-checked:bg-action has-checked:text-on-action has-checked:hover:bg-action",
              "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-focus",
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              id={option.value === value ? id : undefined}
              checked={option.value === value}
              onChange={() => onValueChange(option.value)}
              // The error is read as each radio's description: aria-invalid is not a radio's attribute.
              aria-describedby={error ? errorId : undefined}
              className="sr-only"
            />
            <Icon name={option.icon} size={16} />
            {option.label}
          </label>
        ))}
      </div>
      {/* Always rendered and never display:none (empty, it takes no room): a live region that
          appears together with its text is often not announced. */}
      <p id={noteId} role="status" aria-live="polite" className="text-meta text-ink-2 not-empty:mt-2">
        {note}
      </p>
      </div>
      {error ? (
        <p id={errorId} className="flex items-start gap-1.5 text-meta text-error">
          <Icon name="x-circle" size={15} className="mt-0.5" />
          <span>{error}</span>
        </p>
      ) : null}
    </fieldset>
  );
}
