import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/layout/Shell";
import { ActivityPage } from "./features/activity/ActivityPage";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { AuditPage } from "./features/audit/AuditPage";
import { AuditRecordPage } from "./features/audit/AuditRecordPage";
import { ConsolePage } from "./features/console/ConsolePage";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { GuardianPage } from "./features/guardian/GuardianPage";
import { PolicyPage } from "./features/policy/PolicyPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<DashboardPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="activity" element={<ActivityPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="audit/:decisionId" element={<AuditRecordPage />} />
        <Route path="policy" element={<PolicyPage />} />
        <Route path="console" element={<ConsolePage />} />
      </Route>
      {/* mobile-first, outside the desktop shell */}
      <Route path="guardian" element={<GuardianPage />} />
    </Routes>
  );
}
