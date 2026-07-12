import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/layout/Shell";
import { Page } from "./components/layout/Page";
import { EmptyState } from "./components/ui/States";
import { ActivityPage } from "./features/activity/ActivityPage";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { AuditPage } from "./features/audit/AuditPage";
import { AuditRecordPage } from "./features/audit/AuditRecordPage";
import { PolicyPage } from "./features/policy/PolicyPage";

function ComingSoon({ title, milestone }: { title: string; milestone: string }) {
  return (
    <Page title={title}>
      <EmptyState title={`${title} lands in ${milestone}.`} />
    </Page>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<ComingSoon title="Dashboard" milestone="F4" />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="audit/:decisionId" element={<AuditRecordPage />} />
        <Route path="policy" element={<PolicyPage />} />
        <Route
          path="console"
          element={<ComingSoon title="Console" milestone="F4" />}
        />
      </Route>
    </Routes>
  );
}
