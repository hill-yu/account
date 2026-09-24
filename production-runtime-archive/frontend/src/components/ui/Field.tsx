import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

type BaseProps = {
  label: string;
  hint?: string;
};

type InputProps = BaseProps & {
  as?: "input";
  inputProps?: InputHTMLAttributes<HTMLInputElement>;
};

type SelectProps = BaseProps & {
  as: "select";
  selectProps?: SelectHTMLAttributes<HTMLSelectElement>;
  children: ReactNode;
};

type TextareaProps = BaseProps & {
  as: "textarea";
  textareaProps?: TextareaHTMLAttributes<HTMLTextAreaElement>;
};

type FieldProps = InputProps | SelectProps | TextareaProps;

export function Field(props: FieldProps) {
  return (
    <label className="field">
      <span className="field-label">{props.label}</span>
      {props.as === "select" ? (
        <select className="field-control" {...props.selectProps}>
          {props.children}
        </select>
      ) : props.as === "textarea" ? (
        <textarea className="field-control field-textarea" {...props.textareaProps} />
      ) : (
        <input className="field-control" {...props.inputProps} />
      )}
      {props.hint ? <span className="field-hint">{props.hint}</span> : null}
    </label>
  );
}

