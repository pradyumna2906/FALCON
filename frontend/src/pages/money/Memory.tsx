import { useState } from "react";
import { Alert, Button, Paper, Stack, Typography } from "@mui/material";
import { Form, value } from "../../components/Forms";
import { ConfirmAction } from "../../components/ConfirmAction";
import {
  useResource,
  useFinanceMutation,
  type Schema,
  errorMessage,
} from "../../api/finance";
import { LoadingState } from "../../components/States";

export default function Memory() {
  const [cursor, setCursor] = useState("");
  const categories = useResource<Schema<"CategoryListResponse">>("/categories");
  const query = useResource<Schema<"MerchantMemoryPageResponse">>(
    `/classification/merchant-memories?limit=25${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
  );
  const mutate = useFinanceMutation();
  return (
    <Stack spacing={3}>
      <Alert severity="info">
        Merchant memory applies an exact personal mapping to future
        classification. Review individual transaction categories on the
        Transactions tab.
      </Alert>
      {categories.error && (
        <Alert severity="error">{errorMessage(categories.error)}</Alert>
      )}
      <Paper sx={{ p: 3 }}>
        <Form
          title="Remember a merchant"
          submit="Save merchant memory"
          fields={[
            {
              name: "merchant_name",
              label: "Merchant name",
              required: true,
              maxLength: 200,
            },
            {
              name: "category_id",
              label: "Merchant category",
              required: true,
              options:
                categories.data?.items
                  .filter((c) => c.classification_code)
                  .map((c) => ({
                    value: c.id,
                    label: `${c.name} (${c.kind})`,
                  })) || [],
            },
          ]}
          onSubmit={async (data) => {
            await mutate("/classification/merchant-memories", "PUT", {
              merchant_name: value(data, "merchant_name"),
              category_id: value(data, "category_id"),
            } satisfies Schema<"MerchantMemoryWriteRequest">);
          }}
        />
      </Paper>
      {query.isPending && <LoadingState />}
      {query.error && (
        <Alert severity="error">{errorMessage(query.error)}</Alert>
      )}
      {query.data?.items.length === 0 && (
        <Typography>No saved merchant mappings.</Typography>
      )}
      {query.data?.items.map((item) => (
        <Paper key={item.id} sx={{ p: 2 }}>
          <Typography>
            {item.normalized_merchant} →{" "}
            {item.subcategory_code.replaceAll("_", " ")}
          </Typography>
          <ConfirmAction
            label="Remove merchant memory"
            detail="Future classification will stop using this personal mapping. Existing transaction corrections remain."
            action={() =>
              mutate(`/classification/merchant-memories/${item.id}`, "DELETE")
            }
          />
        </Paper>
      ))}
      <Stack direction="row">
        <Button disabled={!cursor} onClick={() => setCursor("")}>
          First mappings
        </Button>
        <Button
          disabled={!query.data?.next_cursor || query.isFetching}
          onClick={() => setCursor(query.data?.next_cursor || "")}
        >
          Next mappings
        </Button>
      </Stack>
    </Stack>
  );
}
