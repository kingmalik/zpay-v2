'use client'

import { useRef } from 'react'
import { useRouter } from 'next/navigation'
import IntakeForm from '../join/[token]/IntakeForm'

export default function ApplyPage() {
  const router = useRouter()
  const pendingToken = useRef<string>('')

  const handleSubmit = async (values: Record<string, string>) => {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/data/onboarding/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: values }),
    })
    if (!res.ok) throw new Error('apply failed')
    const result = await res.json()
    pendingToken.current = result.token
    return { onboarding_id: result.onboarding_id as number | undefined }
  }

  return (
    <IntakeForm
      token="apply"
      overrideSubmit={handleSubmit}
      onComplete={() => router.replace(`/join/${pendingToken.current}`)}
    />
  )
}
