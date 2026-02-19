# Super Admin Credential Reveal — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let super admins view credential values inline on the `/inventory/credential` list page, with type-aware display (inline reveal for short values, modal for SSH keys/certificates).

**Architecture:** Frontend-only change. The API already returns full credential values. We add a "Value" column to the inventory list table that is only rendered when the current user has the `*` (super admin) permission. Short credential types use the existing `CredentialDisplay` component; long types (ssh_key, certificate) get a "View" button that opens a new modal.

**Tech Stack:** React, TypeScript, shadcn/ui Dialog, existing `CredentialDisplay` component, Zustand auth store.

---

### Task 1: Create CredentialViewModal component

**Files:**
- Create: `frontend/src/components/inventory/CredentialViewModal.tsx`

**Step 1: Create the modal component**

```tsx
import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from 'sonner'

interface CredentialViewModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  name: string
  value: string
}

export function CredentialViewModal({ open, onOpenChange, name, value }: CredentialViewModalProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(value)
    setCopied(true)
    toast.success('Copied to clipboard')
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{name}</DialogTitle>
        </DialogHeader>
        <div className="relative">
          <pre className="bg-muted rounded-md p-4 text-xs font-mono whitespace-pre-wrap break-all max-h-96 overflow-auto">
            {value}
          </pre>
          <Button
            variant="outline"
            size="sm"
            className="absolute top-2 right-2"
            onClick={handleCopy}
          >
            {copied ? <Check className="h-3 w-3 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
            {copied ? 'Copied' : 'Copy'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

**Step 2: Verify it compiles**

Run: `cd /Users/jaketownsend/Desktop/Projectsz/cloudlabmanager && docker compose exec cloudlabmanager bash -c "cd /app/frontend && npx tsc --noEmit 2>&1 | tail -20"` (or equivalent build check)

**Step 3: Commit**

```bash
git add frontend/src/components/inventory/CredentialViewModal.tsx
git commit -m "feat: add CredentialViewModal for viewing long credential values"
```

---

### Task 2: Add Value column to inventory list for super admins

**Files:**
- Modify: `frontend/src/pages/inventory/InventoryHubPage.tsx`

This is the core change. We modify the `columns` useMemo in `InventoryListView` to:
1. Import `useAuthStore`, `CredentialDisplay`, `CredentialViewModal`, and new icons
2. Detect super admin via `permissions.includes('*')`
3. Stop skipping `secret` fields when user is super admin
4. Render type-aware cells: inline `CredentialDisplay` for short types, "View" button for long types
5. Add modal state for the long-value viewer

**Step 1: Add imports at top of file**

At the top of `InventoryHubPage.tsx`, add to the existing imports:

```tsx
// Add Eye to the lucide-react import line
import { Plus, Tag as TagIcon, Search, Trash2, Pencil, Terminal, Monitor, RefreshCw, Square, Eye } from 'lucide-react'

// Add these new imports after the existing ones:
import { useAuthStore } from '@/stores/authStore'
import { CredentialDisplay } from '@/components/portal/CredentialDisplay'
import { CredentialViewModal } from '@/components/inventory/CredentialViewModal'
```

**Step 2: Add super admin check and modal state in `InventoryListView`**

Inside the `InventoryListView` function, after the existing state declarations (after `const [bulkActionOpen, setBulkActionOpen] = useState<string | null>(null)` around line 155), add:

```tsx
  // Super admin credential reveal
  const isSuperAdmin = useAuthStore((s) => s.user?.permissions?.includes('*') ?? false)
  const [credModalOpen, setCredModalOpen] = useState(false)
  const [credModalName, setCredModalName] = useState('')
  const [credModalValue, setCredModalValue] = useState('')
```

**Step 3: Modify the column generation logic**

In the `columns` useMemo (line 249), change the field loop. Replace lines 265-277:

```tsx
    if (typeConfig) {
      const LONG_CRED_TYPES = ['ssh_key', 'certificate']

      for (const field of typeConfig.fields.slice(0, 5)) {
        if (field.name === 'name' || field.type === 'json') continue

        // Secret fields: only show for super admin
        if (field.type === 'secret') {
          if (!isSuperAdmin) continue
          cols.push({
            id: field.name,
            header: field.label || field.name,
            cell: ({ row }) => {
              const val = row.original.data[field.name]
              if (val == null || val === '') return <span className="text-muted-foreground text-xs">—</span>
              const credType = row.original.data.credential_type as string | undefined
              const isLong = credType && LONG_CRED_TYPES.includes(credType)

              if (isLong) {
                return (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={(e) => {
                      e.stopPropagation()
                      setCredModalName(row.original.name)
                      setCredModalValue(String(val))
                      setCredModalOpen(true)
                    }}
                  >
                    <Eye className="h-3 w-3 mr-1" /> View
                  </Button>
                )
              }

              return <CredentialDisplay value={String(val)} />
            },
          })
          continue
        }

        cols.push({
          id: field.name,
          header: field.label || field.name,
          accessorFn: (row) => {
            const val = row.data[field.name]
            return val != null ? String(val) : ''
          },
        })
      }
    }
```

Note: We increase `slice(0, 3)` to `slice(0, 5)` so the `value` field (which is the 4th field in credential.yaml) is included in the iteration.

**Step 4: Add the `useMemo` dependency**

Update the useMemo deps array from `[typeSlug, typeConfig]` to `[typeSlug, typeConfig, isSuperAdmin]`.

**Step 5: Add the modal JSX**

Before the closing `</div>` of `InventoryListView`'s return (just before the final `</div>` around line 543), add:

```tsx
      {/* Credential view modal (super admin) */}
      <CredentialViewModal
        open={credModalOpen}
        onOpenChange={setCredModalOpen}
        name={credModalName}
        value={credModalValue}
      />
```

**Step 6: Verify it compiles and test manually**

1. Build check: verify no TypeScript errors
2. Manual test: Log in as super admin, go to `/inventory/credential`
   - Password/API key/token credentials should show a blurred "Value" column with eye toggle
   - SSH key/certificate credentials should show a "View" button that opens the modal
3. Log in as a non-super-admin user — the Value column should not appear at all

**Step 7: Commit**

```bash
git add frontend/src/pages/inventory/InventoryHubPage.tsx
git commit -m "feat: add credential value column with reveal for super admins"
```
