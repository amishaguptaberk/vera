import { HomePage } from '@/features/pages';
import { PageMain } from '@/features/shell';

// Role-specific landing: analyst → queue, reviewer / card admin → Approvals, cardholder → their request.
export default function Home() {
  return (
    <PageMain>
      <HomePage />
    </PageMain>
  );
}
