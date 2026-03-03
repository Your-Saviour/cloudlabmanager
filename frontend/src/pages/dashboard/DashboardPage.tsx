import { PageHeader } from '@/components/shared/PageHeader'
import { WidgetGrid } from '@/components/dashboard/WidgetGrid'

export default function DashboardPage() {
  return (
    <div>
      <PageHeader title="Dashboard" description="Overview of your CloudLab environment" />
      <WidgetGrid />
    </div>
  )
}
