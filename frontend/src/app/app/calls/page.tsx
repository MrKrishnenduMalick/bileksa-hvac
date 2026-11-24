"use client";

import { useState } from "react";
import { CallsTable } from "@/components/calls-table";
import { Alert, Button, Card, Empty, PageHeader, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { CallRow } from "@/lib/types";
import { useLoad } from "@/lib/use-load";

const PAGE = 50;

export default function CallsPage() {
  const [offset, setOffset] = useState(0);
  const { data, error, loading } = useLoad(
    () => api<{ items: CallRow[]; total: number }>(`/api/calls?limit=${PAGE}&offset=${offset}`),
    [offset],
  );

  return (
    <>
      <PageHeader
        title="Call history"
        subtitle="Every call to your AI receptionist, with the AI's summary. Recordings and transcripts are not stored."
      />
      <Card>
        {loading ? (
          <Spinner />
        ) : error || !data ? (
          <Alert>{error}</Alert>
        ) : data.items.length === 0 ? (
          <Empty title="No calls yet" />
        ) : (
          <>
            <CallsTable calls={data.items} />
            <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
              <span>
                {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  disabled={offset + PAGE >= data.total}
                  onClick={() => setOffset(offset + PAGE)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
