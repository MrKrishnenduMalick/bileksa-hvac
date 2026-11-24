import { Suspense } from "react";
import { Spinner } from "@/components/ui";
import { ClientPage } from "./view";

// A query-string page (/admin/client?id=…) so the site can be exported as static files.
export default function Page() {
  return (
    <Suspense fallback={<Spinner />}>
      <ClientPage />
    </Suspense>
  );
}
