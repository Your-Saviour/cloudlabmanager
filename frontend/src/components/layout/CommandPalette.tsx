import { useNavigate } from 'react-router-dom'
import { Command } from 'cmdk'
import {
  LayoutDashboard,
  Server,
  Play,
  DollarSign,
  Users,
  Shield,
  ScrollText,
  Terminal,
  User,
} from 'lucide-react'
import { useUIStore } from '@/stores/uiStore'
import { useInventoryStore } from '@/stores/inventoryStore'
import { hasPermission } from '@/lib/permissions'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import * as VisuallyHidden from '@radix-ui/react-visually-hidden'

export function CommandPalette() {
  const open = useUIStore((s) => s.commandPaletteOpen)
  const setOpen = useUIStore((s) => s.setCommandPaletteOpen)
  const navigate = useNavigate()
  const types = useInventoryStore((s) => s.types)

  const go = (path: string) => {
    navigate(path)
    setOpen(false)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="overflow-hidden p-0 max-w-lg">
        <VisuallyHidden.Root>
          <DialogTitle>Command Palette</DialogTitle>
        </VisuallyHidden.Root>
        <Command className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]]:px-2 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:h-4 [&_[cmdk-item]_svg]:w-4">
          <Command.Input placeholder="Type a command or search..." className="flex h-11 w-full rounded-md bg-transparent py-3 px-4 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 border-b" />
          <Command.List className="max-h-80 overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">No results found.</Command.Empty>

            <Command.Group heading="Navigation">
              <Command.Item onSelect={() => go('/dashboard')} className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent">
                <LayoutDashboard className="h-4 w-4 text-muted-foreground" /> Dashboard
              </Command.Item>
              <Command.Item onSelect={() => go('/inventory')} className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent">
                <Server className="h-4 w-4 text-muted-foreground" /> Inventory
              </Command.Item>
              <Command.Item onSelect={() => go('/jobs')} className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent">
                <Play className="h-4 w-4 text-muted-foreground" /> Jobs
              </Command.Item>
              {hasPermission('costs.view') && (
                <Command.Item onSelect={() => go('/costs')} className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent">
                  <DollarSign className="h-4 w-4 text-muted-foreground" /> Costs
                </Command.Item>
              )}
            </Command.Group>

            {hasPermission('users.view') && (
              <Command.Group heading="Admin">
                <Command.Item onSelect={() => go('/users')} className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent">
                  <Users className="h-4 w-4 text-muted-foreground" /> Users
                </Command.Item>
                <Command.Item onSelect={() => go('/roles')} className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent">
                  <Shield className="h-4 w-4 text-muted-foreground" /> Roles
                </Command.Item>
                <Command.Item onSelect={() => go('/audit')} className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent">
                  <ScrollText className="h-4 w-4 text-muted-foreground" /> Audit Log
                </Command.Item>
              </Command.Group>
            )}

            <Command.Group heading="Quick Actions">
              <Command.Item onSelect={() => go('/profile')} className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent">
                <User className="h-4 w-4 text-muted-foreground" /> Profile Settings
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  )
}
