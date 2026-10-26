import { PageHeading } from "../components/PageHeading";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
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
  compact = false,
}: {
  message: Schema<"AssistantMessageResponse">;
  suggest: (question: string) => void;
  compact?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const answer = message.answer;
  return (
    <Stack spacing={1.5} sx={{ overflowWrap: "anywhere" }}>
      <Box
        sx={{
          alignSelf: "flex-end",
          maxWidth: "88%",
          bgcolor: "#dcf0e3",
          p: 1.5,
          borderRadius: "14px 14px 3px 14px",
        }}
      >
        <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
          You
        </Typography>
        <Typography sx={{ whiteSpace: "pre-wrap" }}>
          {message.question}
        </Typography>
      </Box>
      <Paper sx={{ p: 2, maxWidth: "94%", borderRadius: "14px 14px 14px 3px" }}>
        <Stack spacing={2}>
          <Typography
            variant="body2"
            sx={{ fontWeight: 750, color: "primary.main" }}
          >
            FALCON AI
          </Typography>
          <Typography variant="body2">
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}{" "}
            · {answer.status} · Reliability: {answer.reliability}
          </Typography>
          <Typography sx={{ whiteSpace: "pre-wrap" }}>
            {answer.answer}
          </Typography>
          <Box component={compact ? "details" : "div"}>
            {compact && (
              <Typography
                component="summary"
                sx={{ cursor: "pointer", fontWeight: 650 }}
              >
                View evidence and reliability
              </Typography>
            )}
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
              {copied
                ? "Copied answer and citations"
                : "Copy answer and citations"}
            </Button>
          </Box>
          {answer.suggested_questions.map((q) => (
            <Button key={q} onClick={() => suggest(q)}>
              {q}
            </Button>
          ))}
        </Stack>
      </Paper>
    </Stack>
  );
}

export default function Assistant({
  embedded = false,
  active = true,
}: {
  embedded?: boolean;
  active?: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const [localId, setLocalId] = useState<string | null>(
    params.get("conversation"),
  );
  const id = embedded ? localId : params.get("conversation");
  const scroll = useRef<HTMLDivElement>(null);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const attempt = useRef<{ id: string; question: string; key: string } | null>(
    null,
  );
  const lock = useRef(false);
  const selectConversation = (next: string | null) => {
    if (embedded) setLocalId(next);
    else setParams(next ? { conversation: next } : {});
    setQuestion("");
    setError("");
    attempt.current = null;
  };
  const cache = useQueryClient();
  const mutate = useFinanceMutation();
  const history = useResource<Schema<"AssistantConversationListResponse">>(
    "/assistant/conversations?limit=20",
  );
  const conversation = useResource<
    Schema<"AssistantConversationDetailResponse">
  >(`/assistant/conversations/${id}?limit=20`, !!id);
  const startConversation = async () => {
    if (lock.current)
      throw new Error("Wait for the current request to finish.");
    lock.current = true;
    setPending(true);
    setError("");
    try {
      const result = await mutate<Schema<"AssistantConversationResponse">>(
        "/assistant/conversations",
        "POST",
      );
      selectConversation(result.id);
    } finally {
      lock.current = false;
      setPending(false);
    }
  };
  useEffect(() => {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [conversation.data?.messages.length, pending, id, active]);
  return (
    <Stack
      spacing={embedded ? 1 : 3}
      sx={embedded ? { height: "100%", minHeight: 0 } : {}}
    >
      {!embedded && (
        <PageHeading
          title="Assistant"
          description="Ask FALCON about your spending, forecasts, goals and possibilities."
          icon="assistant"
        />
      )}
      {!embedded && (
        <Alert severity="info">
          Answers use your financial evidence and show its reliability. Only
          completed, server-verified answers are displayed. Conversations expire
          after 90 days; you can delete them sooner.
        </Alert>
      )}
      {embedded ? (
        <Stack
          direction="row"
          sx={{
            alignItems: "center",
            justifyContent: "space-between",
            gap: 1,
            flexShrink: 0,
          }}
        >
          <Button
            disabled={pending}
            onClick={async () => {
              try {
                await startConversation();
              } catch (cause) {
                setError(errorMessage(cause));
              }
            }}
          >
            {pending && !id ? "Starting…" : "New conversation"}
          </Button>
          <Typography variant="body2" color="text.secondary">
            90-day history
          </Typography>
        </Stack>
      ) : (
        <Paper sx={{ p: 3, bgcolor: "#eaf2ef", borderColor: "#d6e4df" }}>
          <Form
            title="Start a conversation"
            fields={[]}
            submit="New conversation"
            onSubmit={startConversation}
          />
        </Paper>
      )}
      {!id && error && <Alert severity="error">{error}</Alert>}
      <Paper
        component="details"
        sx={{
          p: embedded ? 1 : 2.5,
          flexShrink: 0,
          maxHeight: embedded ? 150 : undefined,
          overflow: "auto",
        }}
      >
        <Typography component="summary" sx={{ fontWeight: 650 }}>
          Recent conversations
        </Typography>
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
                    if (lock.current) return;
                    selectConversation(c.id);
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
      </Paper>
      {!id && (
        <Typography color="text.secondary" sx={{ p: 2 }}>
          Start a new conversation, then ask about your spending, forecasts,
          goals or scenarios. Responses use your financial evidence;
          conversations expire after 90 days.
        </Typography>
      )}
      {id && (
        <Result query={conversation}>
          {(data) => (
            <Stack
              spacing={1}
              sx={embedded ? { flex: 1, minHeight: 0, overflow: "hidden" } : {}}
            >
              <Stack
                direction="row"
                sx={{
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 1,
                  flexShrink: 0,
                }}
              >
                <Typography variant="body2" color="text.secondary">
                  {data.turn_count}/50 turns · Expires{" "}
                  {new Date(data.expires_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}
                </Typography>
                <ConfirmAction
                  label="Delete conversation"
                  detail="Permanently erase this conversation, its messages and associated audit metadata."
                  action={async () => {
                    if (lock.current)
                      throw new Error(
                        "Wait for the current request to finish.",
                      );
                    await mutate(`/assistant/conversations/${id}`, "DELETE");
                    selectConversation(null);
                    setQuestion("");
                    attempt.current = null;
                  }}
                />
              </Stack>
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
              <Box
                ref={scroll}
                role="log"
                aria-label="Chat messages"
                aria-live="polite"
                sx={
                  embedded
                    ? {
                        flex: 1,
                        minHeight: 0,
                        overflowY: "auto",
                        p: 1,
                        bgcolor: "#f1f3eb",
                        display: "grid",
                        gap: 2,
                        alignContent: "start",
                      }
                    : { display: "grid", gap: 2 }
                }
              >
                {data.messages.map((message) => (
                  <Answer
                    key={message.id}
                    message={message}
                    suggest={(text) => {
                      if (!pending) setQuestion(text);
                    }}
                    compact={embedded}
                  />
                ))}
                {pending && (
                  <Box sx={{ p: 1.5, bgcolor: "#dcf0e3", borderRadius: 2 }}>
                    <Typography sx={{ whiteSpace: "pre-wrap" }}>
                      {question}
                    </Typography>
                    <Typography variant="body2" role="status">
                      Preparing a verified answer…
                    </Typography>
                  </Box>
                )}
              </Box>
              <Stack
                component="form"
                spacing={1}
                sx={{ flexShrink: 0 }}
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
                  minRows={embedded ? 1 : 3}
                  maxRows={embedded ? 4 : undefined}
                  placeholder="What would you like to understand about your finances?"
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
                  sx={{ alignSelf: "flex-end", minWidth: 160 }}
                  disabled={pending || data.turn_count >= 50}
                >
                  {pending ? "Sending…" : "Send question"}
                </Button>
              </Stack>
            </Stack>
          )}
        </Result>
      )}
    </Stack>
  );
}
