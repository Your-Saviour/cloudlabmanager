# Credential Reveal V2 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add re-authentication gate before revealing credentials, and make SSH key "View" button fetch the actual private key from the server filesystem via the existing service files API.

**Architecture:** Backend: new `POST /api/auth/verify-identity` endpoint reusing the existing password/TOTP verification pattern. Frontend: new `ReauthDialog` component that gates all credential reveals; SSH key "View" parses `key_path` and fetches the private key via `GET /api/services/{name}/files/{subdir}/{filename}`.

**Tech Stack:** FastAPI (backend), React + TypeScript + shadcn/ui (frontend), existing `verify_password` and `verify_totp` functions.

---

### Task 1: Add `POST /api/auth/verify-identity` backend endpoint

**Files:**
- Modify: `app/models.py` (add request model)
- Modify: `app/routes/auth_routes.py` (add endpoint)

**Step 1: Add the Pydantic request model**

In `app/models.py`, after the `MFADisableRequest` class (around line 184), add:

```python
class VerifyIdentityRequest(BaseModel):
    """Request to POST /api/auth/verify-identity"""
    password: Optional[str] = None
    mfa_code: Optional[str] = None
```

**Step 2: Add the import in auth_routes.py**

In `app/routes/auth_routes.py`, add `VerifyIdentityRequest` to the models import (line 6):

```python
from models import (
    LoginRequest, TokenResponse, SetupRequest, AcceptInviteRequest,
    PasswordResetRequest, PasswordResetConfirm, ChangePasswordRequest,
    UpdateProfileRequest,
    MFAConfirmRequest, MFAVerifyRequest, MFADisableRequest,
    VerifyIdentityRequest,
)
```

**Step 3: Add the endpoint**

After the `/mfa/status` endpoint (around line 312), add:

```python
@router.post("/verify-identity")
async def verify_identity(req: VerifyIdentityRequest,
                          user: User = Depends(get_current_user),
                          session: Session = Depends(get_db_session)):
    """Verify current user's identity via password or MFA code.
    Used as a re-authentication gate before sensitive operations."""
    from database import UserMFA
    from auth import verify_password

    verified = False

    # Try MFA code first
    if req.mfa_code and req.mfa_code.strip().isdigit() and len(req.mfa_code.strip()) == 6:
        mfa = session.query(UserMFA).filter_by(user_id=user.id, is_enabled=True).first()
        if mfa:
            from mfa import decrypt_totp_secret, verify_totp
            secret = decrypt_totp_secret(mfa.totp_secret_encrypted)
            verified = verify_totp(secret, req.mfa_code.strip())

    # Fall back to password
    if not verified and req.password:
        db_user = session.query(User).filter_by(id=user.id).first()
        if db_user:
            verified = verify_password(req.password, db_user.password_hash)

    if not verified:
        raise HTTPException(status_code=400, detail="Invalid password or code")

    return {"verified": True}
```

**Step 4: Commit**

```bash
git add app/models.py app/routes/auth_routes.py
git commit -m "feat: add verify-identity endpoint for re-authentication gate"
```

---

### Task 2: Create ReauthDialog frontend component

**Files:**
- Create: `frontend/src/components/inventory/ReauthDialog.tsx`

**Step 1: Create the component**

```tsx
import { useState } from 'react'
import { KeyRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { toast } from 'sonner'
import api from '@/lib/api'

interface ReauthDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onVerified: () => void
}

export function ReauthDialog({ open, onOpenChange, onVerified }: ReauthDialogProps) {
  const [password, setPassword] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [mfaEnabled, setMfaEnabled] = useState<boolean | null>(null)

  // Check MFA status when dialog opens
  const handleOpenChange = async (isOpen: boolean) => {
    if (isOpen && mfaEnabled === null) {
      try {
        const { data } = await api.get('/api/auth/mfa/status')
        setMfaEnabled(data.mfa_enabled)
      } catch {
        setMfaEnabled(false)
      }
    }
    if (!isOpen) {
      setPassword('')
      setMfaCode('')
    }
    onOpenChange(isOpen)
  }

  const handleSubmit = async () => {
    setLoading(true)
    try {
      await api.post('/api/auth/verify-identity', {
        password: password || undefined,
        mfa_code: mfaCode || undefined,
      })
      setPassword('')
      setMfaCode('')
      onOpenChange(false)
      onVerified()
    } catch {
      toast.error('Verification failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" /> Confirm Identity
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          Re-authenticate to view credential values.
        </p>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Password</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              autoFocus
            />
          </div>
          {mfaEnabled && (
            <div className="space-y-2">
              <Label>MFA Code (alternative)</Label>
              <Input
                type="text"
                inputMode="numeric"
                maxLength={6}
                placeholder="6-digit code"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading || (!password && !mfaCode)}>
            {loading ? 'Verifying...' : 'Verify'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/inventory/ReauthDialog.tsx
git commit -m "feat: add ReauthDialog component for credential re-authentication"
```

---

### Task 3: Wire re-auth gate and SSH key fetch into InventoryHubPage

**Files:**
- Modify: `frontend/src/pages/inventory/InventoryHubPage.tsx`

This is the integration task. We need to:
1. Add re-auth state (grantedUntil timestamp, pending action callback)
2. For inline password reveals: gate behind re-auth, then show CredentialDisplay
3. For SSH key "View": gate behind re-auth, then fetch private key from service files API, then open modal
4. Add ReauthDialog to the JSX

**Step 1: Add imports**

Add to the existing imports at top of `InventoryHubPage.tsx`:

```tsx
import { ReauthDialog } from '@/components/inventory/ReauthDialog'
```

**Step 2: Add re-auth state and helpers**

Inside the `InventoryListView` function, replace the existing credential state block (lines 159-163):

```tsx
  // Credential reveal with re-auth gate
  const canRevealSecrets = useHasPermission(`inventory.${typeSlug}.view`)
  const [credModalOpen, setCredModalOpen] = useState(false)
  const [credModalName, setCredModalName] = useState('')
  const [credModalValue, setCredModalValue] = useState('')
  const [credModalLoading, setCredModalLoading] = useState(false)
  const [reauthOpen, setReauthOpen] = useState(false)
  const [reauthGrantedUntil, setReauthGrantedUntil] = useState(0)
  const pendingActionRef = useRef<(() => void) | null>(null)

  const isReauthValid = () => Date.now() < reauthGrantedUntil

  const requireReauth = (action: () => void) => {
    if (isReauthValid()) {
      action()
    } else {
      pendingActionRef.current = action
      setReauthOpen(true)
    }
  }

  const handleReauthVerified = () => {
    setReauthGrantedUntil(Date.now() + 10 * 60 * 1000) // 10 minutes
    if (pendingActionRef.current) {
      pendingActionRef.current()
      pendingActionRef.current = null
    }
  }
```

Also add `useRef` to the React import at the top of the file:
```tsx
import { useState, useMemo, useRef } from 'react'
```

**Step 3: Add SSH key fetch helper**

After the re-auth helpers (still inside `InventoryListView`), add:

```tsx
  const fetchAndShowPrivateKey = async (name: string, keyPath: string) => {
    // keyPath is like "/services/jump-hosts/outputs/sshkey"
    const match = keyPath.match(/^\/services\/([^/]+)\/([^/]+)\/(.+)$/)
    if (!match) {
      toast.error('Invalid key path')
      return
    }
    const [, serviceName, subdir, filename] = match
    setCredModalName(name)
    setCredModalValue('')
    setCredModalLoading(true)
    setCredModalOpen(true)
    try {
      const { data } = await api.get(`/api/services/${serviceName}/files/${subdir}/${filename}`, {
        responseType: 'text',
        transformResponse: [(d: string) => d],
      })
      setCredModalValue(data)
    } catch {
      toast.error('Failed to fetch private key')
      setCredModalOpen(false)
    } finally {
      setCredModalLoading(false)
    }
  }
```

**Step 4: Update the column cell for secret fields**

Replace the entire secret field column definition inside the `columns` useMemo (the `if (field.type === 'secret')` block, lines 280-313) with:

```tsx
        if (field.type === 'secret') {
          if (!canRevealSecrets) continue
          cols.push({
            id: field.name,
            header: field.label || field.name,
            cell: ({ row }) => {
              const val = row.original.data[field.name]
              const credType = row.original.data.credential_type as string | undefined
              const keyPath = row.original.data.key_path as string | undefined
              const isSSH = credType === 'ssh_key' || credType === 'certificate'

              if (isSSH) {
                if (!keyPath) return <span className="text-muted-foreground text-xs">—</span>
                return (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={(e) => {
                      e.stopPropagation()
                      requireReauth(() => fetchAndShowPrivateKey(row.original.name, keyPath))
                    }}
                  >
                    <Eye className="h-3 w-3 mr-1" /> View Key
                  </Button>
                )
              }

              // Short types (password, api_key, token)
              if (val == null || val === '') return <span className="text-muted-foreground text-xs">—</span>
              return (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={(e) => {
                    e.stopPropagation()
                    requireReauth(() => {
                      setCredModalName(row.original.name)
                      setCredModalValue(String(val))
                      setCredModalOpen(true)
                    })
                  }}
                >
                  <Eye className="h-3 w-3 mr-1" /> Reveal
                </Button>
              )
            },
          })
          continue
        }
```

Key changes:
- SSH keys: uses `keyPath` to fetch private key via service files API, shows "View Key"
- Passwords: shows "Reveal" button instead of inline CredentialDisplay (since we need re-auth first)
- Both go through `requireReauth()` gate

**Step 5: Add ReauthDialog to JSX**

In the JSX return, next to the existing `CredentialViewModal`, add:

```tsx
      {/* Re-authentication dialog */}
      <ReauthDialog
        open={reauthOpen}
        onOpenChange={setReauthOpen}
        onVerified={handleReauthVerified}
      />
```

**Step 6: Update CredentialViewModal to handle loading state**

The modal needs to show a loading state while fetching the SSH key. Pass `credModalLoading` to the modal. Modify the `CredentialViewModal` component in `frontend/src/components/inventory/CredentialViewModal.tsx` to accept an optional `loading` prop:

Update the interface:
```tsx
interface CredentialViewModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  name: string
  value: string
  loading?: boolean
}
```

Update the function signature:
```tsx
export function CredentialViewModal({ open, onOpenChange, name, value, loading }: CredentialViewModalProps) {
```

Replace the `<pre>` block's parent `<div>` with:
```tsx
        <div className="relative">
          {loading ? (
            <div className="bg-muted rounded-md p-4 h-32 flex items-center justify-center">
              <span className="text-sm text-muted-foreground animate-pulse">Loading...</span>
            </div>
          ) : (
            <pre className="bg-muted rounded-md p-4 text-xs font-mono whitespace-pre-wrap break-all max-h-96 overflow-auto">
              {value}
            </pre>
          )}
          {!loading && value && (
            <Button
              variant="outline"
              size="sm"
              className="absolute top-2 right-2"
              onClick={handleCopy}
              aria-label={copied ? 'Copied to clipboard' : 'Copy to clipboard'}
            >
              {copied ? <Check className="h-3 w-3 mr-1" /> : <Copy className="h-3 w-3 mr-1" />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
          )}
        </div>
```

Then in InventoryHubPage.tsx, pass the loading prop:
```tsx
      <CredentialViewModal
        open={credModalOpen}
        onOpenChange={setCredModalOpen}
        name={credModalName}
        value={credModalValue}
        loading={credModalLoading}
      />
```

**Step 7: Commit**

```bash
git add frontend/src/pages/inventory/InventoryHubPage.tsx frontend/src/components/inventory/CredentialViewModal.tsx
git commit -m "feat: wire re-auth gate and SSH key fetch into credential list"
```
