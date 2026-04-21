import TourClientWrapper from '@/components/tour/TourClientWrapper'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <TourClientWrapper>
      {children}
    </TourClientWrapper>
  )
}
