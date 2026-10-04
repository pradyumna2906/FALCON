import { useRef, useState, type ReactNode } from "react";
import {
  Alert,
  Box,
  Button,
  MenuItem,
  InputAdornment,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { errorMessage } from "../api/finance";

export type Field = {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  value?: string;
  options?: readonly (string | { value: string; label: string })[];
  min?: string;
  max?: string;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  help?: string;
};
export function Form({
  title,
  fields,
  submit,
  onSubmit,
  children,
  layout = "default",
}: {
  title: string;
  fields: Field[];
  submit: string;
  onSubmit: (data: FormData) => Promise<void>;
  children?: ReactNode;
  layout?: "default" | "inline";
}) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(false);
  const [visiblePasswords, setVisiblePasswords] = useState<
    Record<string, boolean>
  >({});
  const lock = useRef(false);
  return (
    <Stack
      component="form"
      spacing={2}
      aria-label={title}
      aria-busy={pending}
      onSubmit={async (event) => {
        event.preventDefault();
        if (lock.current) return;
        lock.current = true;
        setPending(true);
        setMessage("");
        setSaved(false);
        const data = new FormData(event.currentTarget);
        try {
          await onSubmit(data);
          setSaved(true);
        } catch (error) {
          setMessage(
            error instanceof InputError ? error.message : errorMessage(error),
          );
        } finally {
          lock.current = false;
          setPending(false);
        }
      }}
    >
      <Typography variant="h2">{title}</Typography>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            sm:
              layout === "inline" || fields.length > 4
                ? "repeat(2, minmax(0, 1fr))"
                : "1fr",
            lg:
              layout === "inline"
                ? `repeat(${Math.min(fields.length, 4)}, minmax(0, 1fr))`
                : fields.length > 4
                  ? "repeat(2, minmax(0, 1fr))"
                  : "1fr",
          },
          gap: 2.5,
          pt: 1,
        }}
      >
        {fields.map((field) => (
          <TextField
            key={field.name}
            name={field.name}
            label={field.label}
            type={
              field.type === "password" && visiblePasswords[field.name]
                ? "text"
                : field.type || "text"
            }
            required={field.required}
            defaultValue={field.value ?? ""}
            select={!!field.options}
            disabled={pending}
            helperText={field.help}
            fullWidth
            autoComplete={
              field.type === "password"
                ? field.name === "new_password"
                  ? "new-password"
                  : field.name === "password"
                    ? "current-password"
                    : "off"
                : field.type === "email"
                  ? "email"
                  : "off"
            }
            slotProps={{
              input:
                field.type === "password"
                  ? {
                      endAdornment: (
                        <InputAdornment position="end">
                          <Button
                            type="button"
                            size="small"
                            aria-label={`${visiblePasswords[field.name] ? "Hide" : "Show"} ${field.label.toLowerCase()}`}
                            aria-pressed={!!visiblePasswords[field.name]}
                            disabled={pending}
                            onClick={() =>
                              setVisiblePasswords((previous) => ({
                                ...previous,
                                [field.name]: !previous[field.name],
                              }))
                            }
                            sx={{ minWidth: 44, px: 1 }}
                          >
                            {visiblePasswords[field.name] ? "Hide" : "Show"}
                          </Button>
                        </InputAdornment>
                      ),
                    }
                  : undefined,
              inputLabel: { shrink: true },
              htmlInput: {
                min: field.min,
                max: field.max,
                minLength: field.minLength,
                maxLength: field.maxLength,
                pattern: field.pattern,
                step: field.type === "number" ? "1" : undefined,
              },
            }}
          >
            {field.options?.map((option) => {
              const value = typeof option === "string" ? option : option.value;
              return (
                <MenuItem key={value} value={value}>
                  {typeof option === "string"
                    ? option.replaceAll("_", " ")
                    : option.label}
                </MenuItem>
              );
            })}
          </TextField>
        ))}
      </Box>
      {children}
      {message && <Alert severity="error">{message}</Alert>}
      {saved && (
        <Alert severity="success" role="status">
          Request completed.
        </Alert>
      )}
      <Button
        type="submit"
        variant="contained"
        disabled={pending}
        sx={{ alignSelf: "flex-start", minWidth: 150 }}
      >
        {pending ? "Working…" : submit}
      </Button>
    </Stack>
  );
}
export class InputError extends Error {}
export function value(data: FormData, name: string) {
  return String(data.get(name) ?? "").trim();
}
export function optional(data: FormData, name: string) {
  return value(data, name) || null;
}
export const currencyField: Field = {
  name: "currency",
  label: "Currency (3-letter code)",
  required: true,
  value: "INR",
  pattern: "[A-Z]{3}",
  maxLength: 3,
};
export const amountField: Field = {
  name: "amount",
  label: "Amount",
  required: true,
  pattern: "[0-9]{1,15}(\\.[0-9]{1,4})?",
  help: "Positive amount, up to 4 decimal places. Currency follows the selected account.",
};
