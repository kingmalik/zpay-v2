'use client'

import { useRouter } from 'next/navigation'
import IntakeForm from '../join/[token]/IntakeForm'

export default function ApplyPage() {
  const router = useRouter()

  const handleSubmit = async (values: Record<string, string>) => {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: values }),
    })
    if (!res.ok) throw new Error('apply failed')
    const result = await res.json()
    router.replace(`/join/${result.token}`)
  }

  return (
    <IntakeForm
      token="apply"
      overrideSubmit={handleSubmit}
      onComplete={() => {}}
    />
  )
}
