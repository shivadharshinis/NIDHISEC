import { Loader2, Save } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router'
import { ApiError } from '../../lib/api'
import { todayIso } from '../../lib/format'
import type { FdrFormValues } from '../../types'
import { Alert, Card, Field, buttonStyles, inputStyles } from '../ui'

// Mirrors backend/app/schemas/fdr.py. The backend re-validates everything.
const BANK_NAME = /^[A-Za-z][A-Za-z0-9 .,&()'-]*$/
const BRANCH = /^[A-Za-z0-9][A-Za-z0-9 .,&()'/-]*$/
const FDR_NUMBER = /^[A-Za-z0-9][A-Za-z0-9 /.-]*$/
const IFSC = /^[A-Z]{4}0[A-Z0-9]{6}$/
const AMOUNT = /^\d{1,11}(\.\d{1,2})?$/
const MAX_AMOUNT = 10_000_000_000
const MAX_TENURE_YEARS = 10

export const EMPTY_FDR_FORM: FdrFormValues = {
  bank_name: '',
  branch_name: '',
  ifsc_code: '',
  fdr_number: '',
  amount: '',
  issue_date: '',
  maturity_date: '',
  remarks: '',
}

type Errors = Partial<Record<keyof FdrFormValues, string>>

function addYears(iso: string, years: number): string {
  const [y, m, d] = iso.split('-')
  const target = `${Number(y) + years}-${m}-${d}`
  return m === '02' && d === '29' ? `${Number(y) + years}-02-28` : target
}

export function validateFdrForm(values: FdrFormValues): Errors {
  const errors: Errors = {}
  const bank = values.bank_name.trim()
  if (!bank) errors.bank_name = 'Issuing bank is required'
  else if (bank.length < 2 || bank.length > 150) errors.bank_name = 'Use 2–150 characters'
  else if (!BANK_NAME.test(bank)) errors.bank_name = 'Use letters, numbers and . , & ( ) \' - only'

  const branch = values.branch_name.trim()
  if (branch && (branch.length > 150 || !BRANCH.test(branch))) errors.branch_name = 'Use up to 150 letters, numbers and basic punctuation'

  const ifsc = values.ifsc_code.trim().toUpperCase()
  if (ifsc && !IFSC.test(ifsc)) errors.ifsc_code = 'IFSC must be 11 characters, e.g. ABCD0123456'

  const number = values.fdr_number.trim()
  if (!number) errors.fdr_number = 'FDR / reference number is required'
  else if (number.length < 3 || number.length > 50) errors.fdr_number = 'Use 3–50 characters'
  else if (!FDR_NUMBER.test(number)) errors.fdr_number = 'Use letters, numbers, spaces and / . - only'

  const amount = values.amount.trim().replace(/,/g, '')
  if (!amount) errors.amount = 'Deposit amount is required'
  else if (amount.startsWith('-') || /^0*(\.0*)?$/.test(amount)) errors.amount = 'Amount must be greater than zero'
  else if (!AMOUNT.test(amount)) errors.amount = 'Enter an amount in rupees with at most 2 decimal places'
  else if (Number(amount) > MAX_AMOUNT) errors.amount = 'Amount exceeds the permitted maximum'

  if (!values.issue_date) errors.issue_date = 'Issue date is required'
  else if (values.issue_date > todayIso()) errors.issue_date = 'Issue date cannot be in the future'

  if (!values.maturity_date) errors.maturity_date = 'Maturity date is required'
  else if (values.issue_date && values.maturity_date <= values.issue_date)
    errors.maturity_date = 'Maturity date must be after the issue date'
  else if (values.issue_date && values.maturity_date > addYears(values.issue_date, MAX_TENURE_YEARS))
    errors.maturity_date = `FDR tenure cannot exceed ${MAX_TENURE_YEARS} years`

  if (values.remarks.length > 1000) errors.remarks = 'Use at most 1000 characters'
  return errors
}

/** Normalise form strings into the API payload shape. */
export function toPayload(values: FdrFormValues) {
  return {
    bank_name: values.bank_name.trim(),
    branch_name: values.branch_name.trim() || null,
    ifsc_code: values.ifsc_code.trim().toUpperCase() || null,
    fdr_number: values.fdr_number.trim(),
    amount: values.amount.trim().replace(/,/g, ''),
    issue_date: values.issue_date,
    maturity_date: values.maturity_date,
    remarks: values.remarks.trim() || null,
  }
}

interface FdrFormProps {
  initialValues: FdrFormValues
  submitLabel: string
  cancelTo: string
  onSubmit: (values: FdrFormValues) => Promise<void>
}

export default function FdrForm({ initialValues, submitLabel, cancelTo, onSubmit }: FdrFormProps) {
  const [values, setValues] = useState(initialValues)
  const [errors, setErrors] = useState<Errors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function set<K extends keyof FdrFormValues>(key: K, value: string) {
    setValues((v) => ({ ...v, [key]: value }))
    if (errors[key]) setErrors((e) => ({ ...e, [key]: undefined }))
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const clientErrors = validateFdrForm(values)
    setErrors(clientErrors)
    setFormError(null)
    if (Object.keys(clientErrors).length > 0) {
      setFormError('Please correct the highlighted fields.')
      return
    }
    setSubmitting(true)
    try {
      await onSubmit(values)
    } catch (error) {
      if (error instanceof ApiError) {
        setErrors(error.fieldErrors as Errors)
        setFormError(error.message)
      } else {
        setFormError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const input = (key: keyof FdrFormValues, extra: Record<string, unknown> = {}) => ({
    id: key,
    name: key,
    value: values[key],
    onChange: (e: { target: { value: string } }) => set(key, e.target.value),
    className: inputStyles,
    'aria-invalid': Boolean(errors[key]),
    'aria-describedby': errors[key] ? `${key}-error` : undefined,
    ...extra,
  })

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      {formError && <Alert tone="error">{formError}</Alert>}

      <Card className="p-5 sm:p-6">
        <h3 className="text-sm font-semibold text-slate-900">Issuing bank</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Field id="bank_name" label="Bank name" required error={errors.bank_name}>
              <input {...input('bank_name', { maxLength: 150, autoComplete: 'off' })} />
            </Field>
          </div>
          <Field id="branch_name" label="Branch" error={errors.branch_name} hint="Optional">
            <input {...input('branch_name', { maxLength: 150, autoComplete: 'off' })} />
          </Field>
          <Field id="ifsc_code" label="Branch IFSC" error={errors.ifsc_code} hint="Optional, e.g. ABCD0123456">
            <input {...input('ifsc_code', { maxLength: 11, autoComplete: 'off', className: `${inputStyles} uppercase` })} />
          </Field>
        </div>
      </Card>

      <Card className="p-5 sm:p-6">
        <h3 className="text-sm font-semibold text-slate-900">Deposit details</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field id="fdr_number" label="FDR / reference number" required error={errors.fdr_number}>
            <input {...input('fdr_number', { maxLength: 50, autoComplete: 'off' })} />
          </Field>
          <Field id="amount" label="Deposit amount (₹)" required error={errors.amount} hint="e.g. 250000.00">
            <input {...input('amount', { inputMode: 'decimal', maxLength: 17, autoComplete: 'off' })} />
          </Field>
          <Field id="issue_date" label="Issue date" required error={errors.issue_date}>
            <input {...input('issue_date', { type: 'date', max: todayIso() })} />
          </Field>
          <Field id="maturity_date" label="Maturity date" required error={errors.maturity_date}>
            <input {...input('maturity_date', { type: 'date', min: values.issue_date || undefined })} />
          </Field>
          <div className="sm:col-span-2">
            <Field id="remarks" label="Remarks" error={errors.remarks} hint="Optional, up to 1000 characters">
              <textarea {...input('remarks', { rows: 3, maxLength: 1000 })} />
            </Field>
          </div>
        </div>
      </Card>

      <Alert tone="info">
        After saving, you can attach the FDR copy and other supporting documents from the record page. Submitting
        records these details for AICTE review; it does not verify the FDR with the bank.
      </Alert>

      <div className="flex flex-wrap justify-end gap-2">
        <Link to={cancelTo} className={buttonStyles.secondary}>Cancel</Link>
        <button type="submit" className={buttonStyles.primary} disabled={submitting}>
          {submitting ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
          {submitting ? 'Saving…' : submitLabel}
        </button>
      </div>
    </form>
  )
}
