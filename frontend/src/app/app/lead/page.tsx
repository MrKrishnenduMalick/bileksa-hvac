import { Suspense } from "react";
import { Spinner } from "@/components/ui";
import { LeadDetailPage } from "./view";

// A query-string page (/app/lead?id=…) so the site can be exported as static files.
export default function Page() {
  return (
    <Suspense fallback={<Spinner />}>
      <LeadDetailPage />
    </Suspense>
  );
}
