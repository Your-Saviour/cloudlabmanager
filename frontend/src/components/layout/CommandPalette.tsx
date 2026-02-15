import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { Command } from 'cmdk'
import { useUIStore } from '@/stores/uiStore'
import { useCommandPaletteStore } from '@/stores/commandPaletteStore'
import { hasPermission } from '@/lib/permissions'
import { Dialog, DialogContent, DialogTitle, DialogHeader, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import * as VisuallyHidden from '@radix-ui/react-visually-hidden'
import { mainRoutes, adminRoutes, quickRoutes, routeIcons, type RouteDefinition } from '@/lib/routes'
import { useCommandActions, formatRelativeTime, type CommandAction } from '@/lib/commandRegistry'
import { useServiceAction } from '@/hooks/useServiceAction'
import { DryRunPreview } from '@/components/services/DryRunPreview'
import { ScriptInputField } from '@/components/shared/ScriptInputField'

const itemClassName = 'flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent'

function RouteItem({ route, go }: { route: RouteDefinition; go: (path: string, item?: { id: string; label: string; icon: string }) => void }) {
  const Icon = routeIcons[route.icon]
  return (
    <Command.Item
      key={route.href}
      value={route.label}
      keywords={route.keywords}
      onSelect={() => go(route.href, { id: route.href, label: route.label, icon: route.icon })}
      className={itemClassName}
    >
      <Icon className="h-4 w-4 text-muted-foreground" /> {route.label}
    </Command.Item>
  )
}

function filterRoutes(routes: RouteDefinition[]): RouteDefinition[] {
  return routes.filter((r) => !r.permission || hasPermission(r.permission))
}

export function CommandPalette() {
  const open = useUIStore((s) => s.commandPaletteOpen)
  const setOpen = useUIStore((s) => s.setCommandPaletteOpen)
  const navigate = useNavigate()
  const [search, setSearch] = useState('')

  const addRecentItem = useCommandPaletteStore((s) => s.addRecentItem)
  const recentItems = useCommandPaletteStore((s) => s.recentItems)

  const go = (path: string, item?: { id: string; label: string; icon: string }) => {
    if (item) {
      addRecentItem({ id: item.id, label: item.label, icon: item.icon, href: path })
    }
    navigate(path)
    setOpen(false)
  }

  const visibleMainRoutes = filterRoutes(mainRoutes)
  const visibleAdminRoutes = filterRoutes(adminRoutes)
  const visibleQuickRoutes = filterRoutes(quickRoutes)
  const { actions, services, inventory, deployCommands, runCommands } = useCommandActions()

  const {
    triggerAction,
    confirmDeploy,
    submitScriptInputs,
    dismissModals,
    dryRunModal,
    scriptModal,
    scriptInputs,
    setScriptInputs,
    isPending,
  } = useServiceAction()

  const visibleServices = services.filter((s) => !s.permission || hasPermission(s.permission))
  const visibleDeployCommands = deployCommands.filter(
    (c) => !c.permission || hasPermission(c.permission)
  )
  const visibleRunCommands = runCommands.filter(
    (c) => !c.permission || hasPermission(c.permission)
  )

  const handleCommandSelect = (cmd: CommandAction) => {
    if (cmd.actionType && cmd.serviceName && cmd.script) {
      setOpen(false)
      setSearch('')
      triggerAction(cmd.serviceName, cmd.objId, cmd.script)
    } else if (cmd.href) {
      go(cmd.href, { id: cmd.id, label: cmd.label, icon: cmd.icon })
    }
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(isOpen) => {
          setOpen(isOpen)
          if (!isOpen) setSearch('')
        }}
      >
        <DialogContent className="overflow-hidden p-0 max-w-lg">
          <VisuallyHidden.Root>
            <DialogTitle>Command Palette</DialogTitle>
          </VisuallyHidden.Root>
          <Command className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]]:px-2 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:h-4 [&_[cmdk-item]_svg]:w-4">
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder="Type a command or search..."
              className="flex h-11 w-full rounded-md bg-transparent py-3 px-4 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 border-b"
            />
            <Command.List className="max-h-80 overflow-y-auto p-2">
              <Command.Empty className="py-6 text-center text-sm text-muted-foreground">No results found.</Command.Empty>

              {search === '' && recentItems.length > 0 && (
                <Command.Group heading="Recent">
                  {recentItems.map((item) => {
                    const Icon = routeIcons[item.icon]
                    return (
                      <Command.Item
                        key={`recent:${item.id}`}
                        value={`recent ${item.label}`}
                        onSelect={() => go(item.href, item)}
                        className={itemClassName}
                      >
                        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
                        {item.label}
                        <span className="ml-auto text-xs text-muted-foreground">
                          {formatRelativeTime(item.timestamp)}
                        </span>
                      </Command.Item>
                    )
                  })}
                </Command.Group>
              )}

              <Command.Group heading="Navigation">
                {visibleMainRoutes.map((route) => (
                  <RouteItem key={route.href} route={route} go={go} />
                ))}
              </Command.Group>

              {visibleDeployCommands.length > 0 && (
                <Command.Group heading="Deploy">
                  {visibleDeployCommands.map((cmd) => {
                    const Icon = routeIcons[cmd.icon]
                    return (
                      <Command.Item
                        key={cmd.id}
                        value={cmd.label}
                        keywords={cmd.keywords}
                        onSelect={() => handleCommandSelect(cmd)}
                        className={itemClassName}
                      >
                        <Icon className="h-4 w-4 text-muted-foreground" />
                        <span>{cmd.label}</span>
                      </Command.Item>
                    )
                  })}
                </Command.Group>
              )}

              {visibleRunCommands.length > 0 && (
                <Command.Group heading="Run Script">
                  {visibleRunCommands.map((cmd) => {
                    const Icon = routeIcons[cmd.icon]
                    return (
                      <Command.Item
                        key={cmd.id}
                        value={cmd.label}
                        keywords={cmd.keywords}
                        onSelect={() => handleCommandSelect(cmd)}
                        className={itemClassName}
                      >
                        <Icon className="h-4 w-4 text-muted-foreground" />
                        <span>{cmd.label}</span>
                      </Command.Item>
                    )
                  })}
                </Command.Group>
              )}

              {visibleServices.length > 0 && (
                <Command.Group heading="Services">
                  {visibleServices.map((svc) => {
                    const Icon = routeIcons[svc.icon]
                    return (
                      <Command.Item
                        key={svc.id}
                        value={svc.label}
                        keywords={svc.keywords}
                        onSelect={() => go(svc.href!, { id: svc.id, label: svc.label, icon: svc.icon })}
                        className={itemClassName}
                      >
                        <Icon className="h-4 w-4 text-muted-foreground" />
                        <span>{svc.label}</span>
                        {svc.sublabel && (
                          <span className={cn('ml-auto text-xs', svc.sublabel === 'Running' ? 'text-green-500' : 'text-muted-foreground')}>{svc.sublabel}</span>
                        )}
                      </Command.Item>
                    )
                  })}
                </Command.Group>
              )}

              {inventory.length > 0 && (
                <Command.Group heading="Inventory">
                  {inventory.map((inv) => {
                    const Icon = routeIcons[inv.icon]
                    return (
                      <Command.Item
                        key={inv.id}
                        value={inv.label}
                        keywords={inv.keywords}
                        onSelect={() => go(inv.href!, { id: inv.id, label: inv.label, icon: inv.icon })}
                        className={itemClassName}
                      >
                        <Icon className="h-4 w-4 text-muted-foreground" /> {inv.label}
                      </Command.Item>
                    )
                  })}
                </Command.Group>
              )}

              {actions.length > 0 && (
                <Command.Group heading="Actions">
                  {actions.map((action) => {
                    const Icon = routeIcons[action.icon]
                    return (
                      <Command.Item
                        key={action.id}
                        value={action.label}
                        keywords={action.keywords}
                        onSelect={() => go(action.href!, { id: action.id, label: action.label, icon: action.icon })}
                        className={itemClassName}
                      >
                        <Icon className="h-4 w-4 text-muted-foreground" /> {action.label}
                      </Command.Item>
                    )
                  })}
                </Command.Group>
              )}

              {visibleAdminRoutes.length > 0 && (
                <Command.Group heading="Admin">
                  {visibleAdminRoutes.map((route) => (
                    <RouteItem key={route.href} route={route} go={go} />
                  ))}
                </Command.Group>
              )}

              <Command.Group heading="Quick Actions">
                {visibleQuickRoutes.map((route) => (
                  <RouteItem key={route.href} route={route} go={go} />
                ))}
              </Command.Group>
            </Command.List>
          </Command>
        </DialogContent>
      </Dialog>

      {dryRunModal && (
        <DryRunPreview
          serviceName={dryRunModal.serviceName}
          open={true}
          onOpenChange={(open) => { if (!open) dismissModals() }}
          onConfirm={confirmDeploy}
        />
      )}

      {scriptModal && (
        <Dialog open={true} onOpenChange={() => dismissModals()}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{scriptModal.script.label || scriptModal.script.name}</DialogTitle>
              <p className="text-sm text-muted-foreground">Configure inputs for this script</p>
            </DialogHeader>
            <div className="space-y-4">
              {scriptModal.script.inputs?.map((inp) => (
                <ScriptInputField
                  key={inp.name}
                  input={inp}
                  value={scriptInputs[inp.name] ?? (inp.type === 'list' ? [''] : inp.type === 'ssh_key_select' ? [] : '')}
                  onChange={(val) => setScriptInputs({ ...scriptInputs, [inp.name]: val })}
                  serviceName={scriptModal.serviceName}
                />
              ))}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={dismissModals}>Cancel</Button>
              <Button onClick={submitScriptInputs} disabled={isPending}>Run</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
