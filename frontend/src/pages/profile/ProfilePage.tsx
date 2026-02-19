import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, Key, User, Download, Copy, ShieldCheck, ShieldOff, RefreshCw, Upload, Trash2 } from 'lucide-react'
import api from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { PageHeader } from '@/components/shared/PageHeader'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { toast } from 'sonner'

export default function ProfilePage() {
  const queryClient = useQueryClient()
  const user = useAuthStore((s) => s.user)

  const [displayName, setDisplayName] = useState(user?.display_name || '')
  const [email, setEmail] = useState(user?.email || '')

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const [privateKeyDialog, setPrivateKeyDialog] = useState<string | null>(null)
  const [regenConfirmOpen, setRegenConfirmOpen] = useState(false)

  // MFA state
  const [mfaStep, setMfaStep] = useState<'idle' | 'enrolling' | 'confirming'>('idle')
  const [enrollData, setEnrollData] = useState<{ qr_code: string; totp_secret: string } | null>(null)
  const [confirmCode, setConfirmCode] = useState('')
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null)
  const [disableCode, setDisableCode] = useState('')
  const [disableDialogOpen, setDisableDialogOpen] = useState(false)

  // Personal SSH key state
  const [personalKey, setPersonalKey] = useState('')
  const [personalKeyError, setPersonalKeyError] = useState('')

  const { data: existingKey } = useQuery({
    queryKey: ['ssh-key'],
    queryFn: async () => {
      const { data } = await api.get('/api/auth/me/ssh-key')
      return data.ssh_public_key as string | null
    },
  })

  const updateProfileMutation = useMutation({
    mutationFn: () => api.put('/api/auth/me', { display_name: displayName, email }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
      toast.success('Profile updated')
    },
    onError: () => toast.error('Update failed'),
  })

  const changePasswordMutation = useMutation({
    mutationFn: () =>
      api.post('/api/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      }),
    onSuccess: () => {
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      toast.success('Password changed')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Password change failed'),
  })

  const generateKeyMutation = useMutation({
    mutationFn: () => api.post('/api/auth/me/ssh-key'),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['ssh-key'] })
      const privateKey = res.data.private_key
      if (privateKey) {
        setPrivateKeyDialog(privateKey)
      } else {
        toast.success('SSH key generated')
      }
    },
    onError: () => toast.error('Key generation failed'),
  })

  const deleteKeyMutation = useMutation({
    mutationFn: () => api.delete('/api/auth/me/ssh-key'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ssh-key'] })
      toast.success('SSH key removed')
    },
    onError: () => toast.error('Remove failed'),
  })

  const { data: meData } = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: async () => {
      const { data } = await api.get('/api/auth/me')
      return data as { personal_ssh_public_key: string | null }
    },
  })

  const existingPersonalKey = meData?.personal_ssh_public_key || null

  // Sync personal key textarea with server data
  useEffect(() => {
    if (existingPersonalKey && !personalKey) {
      setPersonalKey(existingPersonalKey)
    }
  }, [existingPersonalKey])

  const VALID_KEY_PREFIXES = ['ssh-rsa', 'ssh-ed25519', 'ecdsa-sha2-', 'ssh-dss']

  const savePersonalKeyMutation = useMutation({
    mutationFn: () => api.put('/api/auth/me/personal-ssh-key', { key: personalKey }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
      setPersonalKeyError('')
      toast.success('Personal SSH key saved')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to save key'),
  })

  const removePersonalKeyMutation = useMutation({
    mutationFn: () => api.delete('/api/auth/me/personal-ssh-key'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
      setPersonalKey('')
      setPersonalKeyInitialized(false)
      toast.success('Personal SSH key removed')
    },
    onError: () => toast.error('Failed to remove key'),
  })

  const handleSavePersonalKey = () => {
    const trimmed = personalKey.trim()
    if (!trimmed) {
      setPersonalKeyError('Key cannot be empty')
      return
    }
    if (!VALID_KEY_PREFIXES.some(prefix => trimmed.startsWith(prefix))) {
      setPersonalKeyError('Key must start with ssh-rsa, ssh-ed25519, ecdsa-sha2-, or ssh-dss')
      return
    }
    setPersonalKeyError('')
    savePersonalKeyMutation.mutate()
  }

  const { data: mfaStatus, refetch: refetchMfaStatus } = useQuery({
    queryKey: ['mfa-status'],
    queryFn: async () => {
      const { data } = await api.get('/api/auth/mfa/status')
      return data as { mfa_enabled: boolean; enrolled_at: string | null; backup_codes_remaining: number }
    },
  })

  const enrollMutation = useMutation({
    mutationFn: () => api.post('/api/auth/mfa/enroll'),
    onSuccess: (res) => {
      setEnrollData({ qr_code: res.data.qr_code, totp_secret: res.data.totp_secret })
      setMfaStep('enrolling')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to start enrollment'),
  })

  const confirmMutation = useMutation({
    mutationFn: () => api.post('/api/auth/mfa/confirm', { code: confirmCode }),
    onSuccess: (res) => {
      setBackupCodes(res.data.backup_codes)
      setMfaStep('idle')
      setEnrollData(null)
      setConfirmCode('')
      refetchMfaStatus()
      toast.success('Two-factor authentication enabled')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Invalid code'),
  })

  const disableMutation = useMutation({
    mutationFn: () => api.post('/api/auth/mfa/disable', { code: disableCode }),
    onSuccess: () => {
      setDisableDialogOpen(false)
      setDisableCode('')
      refetchMfaStatus()
      toast.success('Two-factor authentication disabled')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to disable MFA'),
  })

  const regenBackupMutation = useMutation({
    mutationFn: () => api.post('/api/auth/mfa/backup-codes/regenerate'),
    onSuccess: (res) => {
      setBackupCodes(res.data.backup_codes)
      refetchMfaStatus()
      toast.success('Backup codes regenerated')
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Failed to regenerate codes'),
  })

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    toast.success('Copied to clipboard')
  }

  const downloadPrivateKey = (key: string) => {
    const blob = new Blob([key], { type: 'application/x-pem-file' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'cloudlab_key.pem'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <PageHeader title="Profile" description="Manage your account settings" />

      <div className="grid gap-6 max-w-2xl">
        {/* Profile Info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <User className="h-4 w-4" /> Profile Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Username</Label>
              <Input value={user?.username || ''} disabled />
            </div>
            <div className="space-y-2">
              <Label>Display Name</Label>
              <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <Button size="sm" onClick={() => updateProfileMutation.mutate()} disabled={updateProfileMutation.isPending}>
              <Save className="mr-2 h-3 w-3" /> Save
            </Button>
          </CardContent>
        </Card>

        {/* Change Password */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Key className="h-4 w-4" /> Change Password
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Current Password</Label>
              <Input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>New Password</Label>
              <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Confirm New Password</Label>
              <Input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
            </div>
            {newPassword && confirmPassword && newPassword !== confirmPassword && (
              <p className="text-sm text-destructive">Passwords do not match</p>
            )}
            <Button
              size="sm"
              onClick={() => changePasswordMutation.mutate()}
              disabled={!currentPassword || !newPassword || newPassword !== confirmPassword || changePasswordMutation.isPending}
            >
              Change Password
            </Button>
          </CardContent>
        </Card>

        {/* SSH Key */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">SSH Key</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {existingKey ? (
              <>
                <div className="bg-muted/30 rounded-md p-3 font-mono text-xs break-all">
                  {existingKey}
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setRegenConfirmOpen(true)}
                    disabled={generateKeyMutation.isPending}
                  >
                    Regenerate Key
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => deleteKeyMutation.mutate()}>
                    Remove Key
                  </Button>
                </div>
              </>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  No SSH key configured. Generate one to enable SSH access to instances.
                </p>
                <Button
                  size="sm"
                  onClick={() => generateKeyMutation.mutate()}
                  disabled={generateKeyMutation.isPending}
                >
                  <Key className="mr-2 h-3 w-3" /> Generate SSH Key
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Personal SSH Key */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Upload className="h-4 w-4" /> Personal SSH Key
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Upload your personal SSH public key. When credential access rules require
              a personal key, this key will be used instead of shared credentials.
            </p>
            <Textarea
              placeholder="Paste your SSH public key here (ssh-rsa AAAA... or ssh-ed25519 AAAA...)"
              value={personalKey}
              onChange={(e) => { setPersonalKey(e.target.value); setPersonalKeyError('') }}
              rows={4}
              className="font-mono text-sm"
            />
            {personalKeyError && <p className="text-destructive text-sm">{personalKeyError}</p>}
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={handleSavePersonalKey}
                disabled={savePersonalKeyMutation.isPending}
              >
                <Save className="mr-2 h-3 w-3" /> Save Personal Key
              </Button>
              {existingPersonalKey && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => removePersonalKeyMutation.mutate()}
                  disabled={removePersonalKeyMutation.isPending}
                >
                  <Trash2 className="mr-2 h-3 w-3" /> Remove
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Two-Factor Authentication */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" /> Two-Factor Authentication
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {mfaStep === 'enrolling' && enrollData ? (
              /* Enrollment: QR code + confirm */
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.)
                </p>
                <div className="flex justify-center">
                  <img
                    src={`data:image/png;base64,${enrollData.qr_code}`}
                    alt="MFA QR Code"
                    className="rounded-lg border"
                    width={200}
                    height={200}
                  />
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">Or enter this code manually:</p>
                  <div className="bg-muted/30 rounded-md p-2 font-mono text-xs text-center tracking-widest select-all">
                    {enrollData.totp_secret}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="mfa-confirm-code">Enter the 6-digit code from your app to confirm</Label>
                  <div className="flex gap-2">
                    <Input
                      id="mfa-confirm-code"
                      value={confirmCode}
                      onChange={(e) => setConfirmCode(e.target.value)}
                      placeholder="000000"
                      className="text-center tracking-widest max-w-[160px]"
                      maxLength={6}
                      autoFocus
                    />
                    <Button
                      size="sm"
                      onClick={() => confirmMutation.mutate()}
                      disabled={confirmCode.length !== 6 || confirmMutation.isPending}
                    >
                      Confirm
                    </Button>
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => { setMfaStep('idle'); setEnrollData(null); setConfirmCode('') }}>
                  Cancel
                </Button>
              </div>
            ) : mfaStatus?.mfa_enabled ? (
              /* MFA Enabled: status + management */
              <div className="space-y-4">
                <div className="flex items-center gap-2 text-sm">
                  <ShieldCheck className="h-4 w-4 text-green-500" />
                  <span className="text-green-600 dark:text-green-400 font-medium">Enabled</span>
                  {mfaStatus.enrolled_at && (
                    <span className="text-muted-foreground">
                      since {new Date(mfaStatus.enrolled_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
                <p className="text-sm text-muted-foreground">
                  Backup codes remaining: <span className="font-medium">{mfaStatus.backup_codes_remaining}</span>
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => regenBackupMutation.mutate()}
                    disabled={regenBackupMutation.isPending}
                  >
                    <RefreshCw className="mr-2 h-3 w-3" /> Regenerate Backup Codes
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setDisableDialogOpen(true)}
                  >
                    <ShieldOff className="mr-2 h-3 w-3" /> Disable MFA
                  </Button>
                </div>
              </div>
            ) : (
              /* MFA Not Enabled */
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  Add an extra layer of security to your account by enabling two-factor authentication.
                </p>
                <Button
                  size="sm"
                  onClick={() => enrollMutation.mutate()}
                  disabled={enrollMutation.isPending}
                >
                  <ShieldCheck className="mr-2 h-3 w-3" /> Enable Two-Factor Authentication
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Private Key Dialog */}
      <Dialog open={!!privateKeyDialog} onOpenChange={() => setPrivateKeyDialog(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>SSH Private Key</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-destructive font-medium">
              Save this private key now. It cannot be retrieved again.
            </p>
            <Textarea
              value={privateKeyDialog || ''}
              readOnly
              rows={12}
              className="font-mono text-xs"
            />
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => privateKeyDialog && copyToClipboard(privateKeyDialog)}
              >
                <Copy className="mr-2 h-3 w-3" /> Copy
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => privateKeyDialog && downloadPrivateKey(privateKeyDialog)}
              >
                <Download className="mr-2 h-3 w-3" /> Download .pem
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setPrivateKeyDialog(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Regenerate Confirm */}
      <ConfirmDialog
        open={regenConfirmOpen}
        onOpenChange={setRegenConfirmOpen}
        title="Regenerate SSH Key"
        description="This will replace your current SSH key. The old key will stop working immediately. Continue?"
        confirmLabel="Regenerate"
        variant="destructive"
        onConfirm={() => {
          setRegenConfirmOpen(false)
          generateKeyMutation.mutate()
        }}
      />

      {/* Backup Codes Dialog */}
      <Dialog open={!!backupCodes} onOpenChange={() => setBackupCodes(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Backup Codes</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-destructive font-medium">
              Save these backup codes in a secure location. Each code can only be used once.
              They will not be shown again.
            </p>
            <div className="bg-muted/30 rounded-md p-4 grid grid-cols-2 gap-2 font-mono text-sm">
              {backupCodes?.map((code, i) => (
                <div key={i} className="text-center">{code}</div>
              ))}
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => backupCodes && copyToClipboard(backupCodes.join('\n'))}
              >
                <Copy className="mr-2 h-3 w-3" /> Copy
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  if (!backupCodes) return
                  const blob = new Blob([backupCodes.join('\n')], { type: 'text/plain' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = 'cloudlab-backup-codes.txt'
                  document.body.appendChild(a)
                  a.click()
                  document.body.removeChild(a)
                  URL.revokeObjectURL(url)
                }}
              >
                <Download className="mr-2 h-3 w-3" /> Download
              </Button>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setBackupCodes(null)}>I've saved these codes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Disable MFA Dialog */}
      <Dialog open={disableDialogOpen} onOpenChange={(open) => { setDisableDialogOpen(open); if (!open) setDisableCode('') }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Disable Two-Factor Authentication</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Label htmlFor="mfa-disable-code" className="text-sm text-muted-foreground font-normal">
              Enter your current 6-digit authenticator code to confirm.
            </Label>
            <Input
              id="mfa-disable-code"
              value={disableCode}
              onChange={(e) => setDisableCode(e.target.value)}
              placeholder="000000"
              className="text-center tracking-widest"
              maxLength={6}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDisableDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => disableMutation.mutate()}
              disabled={disableCode.length !== 6 || disableMutation.isPending}
            >
              Disable MFA
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
