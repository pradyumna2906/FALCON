import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useSearchParams } from "react-router";
import { api } from "../api/client";
import {
  errorMessage,
  useFinanceMutation,
  useResource,
  type Schema,
} from "../api/finance";
import { ConfirmAction } from "../components/ConfirmAction";
import { Form } from "../components/Forms";
import { DataTable, Reasons, Result } from "../components/FinancialResults";

export function Answer({
  message,
  suggest,
}: {
  message: Schema<"AssistantMessageResponse">;
  suggest: (question: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const answer = message.answer;
  return (
    <Paper sx={{ p: 2, overflowWrap: "anywhere" }}>
      <Stack spacing={2}>
        <Typography variant="h2">{message.question}</Typography>
        <Typography variant="body2">
          {message.created_at} · {answer.status} · Reliability:{" "}
          {answer.reliability}
        </Typography>
        <Typography sx={{ whiteSpace: "pre-wrap" }}>{answer.answer}</Typography>
        <Reasons items={answer.evidence_summary} />
        <Reasons items={answer.warnings} />
        {answer.refusal_reason && (
          <Alert severity="warning">
            {answer.refusal_reason.replaceAll("_", " ")}
          </Alert>
        )}
        <DataTable
          title="Verified evidence citations"
          headings={[
            "Source",
            "Evidence",
            "Reference",
            "Cutoff",
            "Reliability",
          ]}
          rows={answer.citations.map((c) => [
            c.source,
            c.label,
            c.reference,
            c.cutoff_at,
            c.reliability,
          ])}
        />
        <Button
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(
                `${answer.answer}\n\n${answer.citations.map((c) => `${c.label}: ${c.reference} (${c.cutoff_at})`).join("\n")}`,
              );
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? "Copied answer and citations" : "Copy answer and citations"}
        </Button>
        {answer.suggested_questions.map((q) => (
          <Button key={q} onClick={() => suggest(q)}>
            {q}
          </Button>
        ))}
      </Stack>
    </Paper>
  );
}

export default function Assistant() {
  const [params, setParams] = useSearchParams();
  const id = params.get("conversation");
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const attempt = useRef<{ id: string; question: string; key: string } | null>(
    null,
  );
  const lock = useRef(false);
  const cache = useQueryClient();
  const mutate = useFinanceMutation();
  const history = useResource<Schema<"AssistantConversationListResponse">>(
    "/assistant/conversations?limit=20",
  );
  const conversation = useResource<
    Schema<"AssistantConversationDetailResponse">
  >(`/assistant/conversations/${id}?limit=20`, !!id);
  return (
    <Stack spacing={3}>
      <Typography variant="h1">Assistant</Typography>
      <Alert severity="info">
        Answers use your financial evidence and show its reliability. Only
        completed, server-verified answers are displayed. Conversations expire
        after 90 days; you can delete them sooner.
      </Alert>
      <Form
        title="Start a conversation"
        fields={[]}
        submit="New conversation"
        onSubmit={async () => {
          const result = await mutate<Schema<"AssistantConversationResponse">>(
            "/assistant/conversations",
            "POST",
          );
          setParams({ conversation: result.id });
          setQuestion("");
          setError("");
        }}
      />
      <Result query={history}>
        {(data) => (
          <DataTable
            title="Recent conversations (up to 20)"
            headings={["Created", "Expires", "Turns", "Open"]}
            rows={data.items.map((c) => [
              c.created_at,
              c.expires_at,
              c.turn_count,
              <Button
                onClick={() => {
                  setParams({ conversation: c.id });
                  setQuestion("");
                  setError("");
                }}
              >
                Open {c.id}
              </Button>,
            ])}
          />
        )}
      </Result>
      {id && (
        <Result query={conversation}>
          {(data) => (
            <Stack spacing={2}>
              <Typography>
                Expires {data.expires_at} · {data.turn_count}/50 turns
              </Typography>
              <ConfirmAction
                label="Delete conversation"
                detail="Permanently erase this conversation, its messages and associated audit metadata."
                action={async () => {
                  await mutate(`/assistant/conversations/${id}`, "DELETE");
                  setParams({});
                  setQuestion("");
                  attempt.current = null;
                }}
              />
              {data.has_more && (
                <Alert severity="info">
                  Showing the most recent 20 turns. Your whole-user export
                  includes retained conversation history.
                </Alert>
              )}
              {data.messages.length === 0 && (
                <Alert severity="info">
                  Ask about your spending, forecasts, goal plan or scenario
                  results.
                </Alert>
              )}
              {data.messages.map((message) => (
                <Answer
                  key={message.id}
                  message={message}
                  suggest={setQuestion}
                />
              ))}
              <Stack
                component="form"
                spacing={2}
                aria-label="Ask the assistant"
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (lock.current || !question.trim()) return;
                  lock.current = true;
                  setPending(true);
                  setError("");
                  const text = question.trim();
                  if (
                    !attempt.current ||
                    attempt.current.id !== id ||
                    attempt.current.question !== text
                  )
                    attempt.current = {
                      id,
                      question: text,
                      key: crypto.randomUUID(),
                    };
                  try {
                    await api.request(
                      `/assistant/conversations/${id}/messages`,
                      {
                        method: "POST",
                        headers: { "Idempotency-Key": attempt.current.key },
                        body: JSON.stringify({ question: text }),
                      },
                    );
                    attempt.current = null;
                    setQuestion("");
                    await cache.invalidateQueries({ queryKey: ["finance"] });
                  } catch (cause) {
                    setError(
                      `${errorMessage(cause)} No unverified answer is shown. Retry the unchanged question to safely recover the same request.`,
                    );
                  } finally {
                    lock.current = false;
                    setPending(false);
                  }
                }}
              >
                <TextField
                  label="Your question"
                  multiline
                  minRows={3}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  required
                  disabled={pending}
                  slotProps={{ htmlInput: { maxLength: 2000 } }}
                />
                {error && <Alert severity="error">{error}</Alert>}
                <Button
                  type="submit"
                  variant="contained"
                  disabled={pending || data.turn_count >= 50}
                >
                  {pending ? "Preparing a verified answer…" : "Send question"}
                </Button>
              </Stack>
            </Stack>
          )}
        </Result>
      )}
    </Stack>
  );
}
