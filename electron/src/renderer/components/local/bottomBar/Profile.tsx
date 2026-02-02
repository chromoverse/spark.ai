import React, { useEffect, useState } from "react";
import {
    User,
    Bell,
    Shield,
    Globe,
    Sparkles,
    LogOut,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { setClientOffline, setClientOnline } from "@/store/features/localState/localSlice";
import { useNavigate } from "react-router-dom";
import { resetUser } from "@/store/features/auth/authSlice";

// Profile Dropdown Component
export default function ProfileDropdown() {
    const navigate = useNavigate()
    const dispatch = useAppDispatch()
    const logout = async() => {
        await window.electronApi.deleteToken("access_token")
        await window.electronApi.deleteToken("refresh_token")
        dispatch(resetUser())
        navigate("/auth/lander")
    }
  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-neutral-400 hover:text-white hover:bg-white/10"
            >
              <User size={16} />
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent side="top">
          <p>Profile</p>
        </TooltipContent>
      </Tooltip>

      <DropdownMenuContent className="w-56" align="end" side="top">
        <DropdownMenuLabel>My Account</DropdownMenuLabel>
        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuItem>
            <User className="mr-2 h-4 w-4" />
            <span>Profile Settings</span>
          </DropdownMenuItem>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <Sparkles className="mr-2 h-4 w-4" />
              <span>AI Preferences</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuPortal>
              <DropdownMenuSubContent>
                <DropdownMenuItem>Creative Mode</DropdownMenuItem>
                <DropdownMenuItem>Balanced Mode</DropdownMenuItem>
                <DropdownMenuItem>Precise Mode</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem>Custom Settings...</DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuPortal>
          </DropdownMenuSub>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <Globe className="mr-2 h-4 w-4" />
              <span>Region</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuPortal>
              <DropdownMenuSubContent>
                <DropdownMenuItem>United States</DropdownMenuItem>
                <DropdownMenuItem>United Kingdom</DropdownMenuItem>
                <DropdownMenuItem>Europe</DropdownMenuItem>
                <DropdownMenuItem>Asia Pacific</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem>Other regions...</DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuPortal>
          </DropdownMenuSub>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuItem>
            <Shield className="mr-2 h-4 w-4" />
            <span>Security</span>
          </DropdownMenuItem>
          <DropdownMenuItem>
            <Bell className="mr-2 h-4 w-4" />
            <span>Notifications</span>
          </DropdownMenuItem>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuItem onClick={() => logout()} className="text-red-500 focus:text-red-500">
          <LogOut className="mr-2 h-4 w-4" />
          <span>Log out</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
