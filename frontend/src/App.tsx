import { Route, Routes } from "react-router-dom";
import { Shell } from "./components/layout/Shell";
import { Page } from "./components/layout/Page";
import { EmptyState } from "./components/ui/States";

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
        <Route
          path="approvals"
          element={<ComingSoon title="Approvals" milestone="F2" />}
        />
        <Route
          path="activity"
          element={<ComingSoon title="Activity" milestone="F3" />}
        />
        <Route path="audit" element={<ComingSoon title="Audit" milestone="F3" />} />
        <Route path="policy" element={<ComingSoon title="Policy" milestone="F2" />} />
        <Route
          path="console"
          element={<ComingSoon title="Console" milestone="F4" />}
        />
      </Route>
    </Routes>
  );
}
