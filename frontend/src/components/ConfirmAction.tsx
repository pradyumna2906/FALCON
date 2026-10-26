import { useRef, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import { errorMessage } from "../api/finance";

export function ConfirmAction({
  label,
  detail,
  action,
}: {
  label: string;
  detail: string;
  action: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  return (
    <>
      <Button
        color="error"
        onClick={() => {
          setError("");
          setOpen(true);
        }}
      >
        {label}
      </Button>
      <Dialog
        open={open}
        onClose={() => {
          if (!pending) setOpen(false);
        }}
        aria-labelledby="confirm-action-title"
      >
        <DialogTitle id="confirm-action-title">{label}?</DialogTitle>
        <DialogContent>
          {detail}
          {error && <Alert severity="error">{error}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button disabled={pending} onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            color="error"
            disabled={pending}
            onClick={async () => {
              if (lock.current) return;
              lock.current = true;
              setPending(true);
              setError("");
              try {
                await action();
                setOpen(false);
              } catch (cause) {
                setError(errorMessage(cause));
              } finally {
                setPending(false);
                lock.current = false;
              }
            }}
          >
            {pending ? "Working…" : "Confirm"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
