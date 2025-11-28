"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import ProfileForm from "./ProfileForm";
import { fetchUserProfile } from "@/app/api/profile";
import { UserProfile } from "@/app/types/profile";

type ProfileOnboardingDialogProps = {
  userId: string | null;
  onCompleted?: (profile: UserProfile) => void;
};

export default function ProfileOnboardingDialog({
  userId,
  onCompleted,
}: ProfileOnboardingDialogProps) {
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    const verify = async () => {
      if (!userId) return;
      setChecking(true);
      const response = await fetchUserProfile(userId);
      setChecking(false);
      if (!response.profile) {
        setOpen(true);
      }
    };
    verify();
  }, [userId]);

  if (!userId) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !checking && setOpen(value)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Tell us about you</DialogTitle>
          <DialogDescription>
            We use your profile to personalize meal plans before you start
            chatting with the agent.
          </DialogDescription>
        </DialogHeader>
        <ProfileForm
          userId={userId}
          submitLabel="Save and Continue"
          compact
          onSaved={(profile) => {
            setOpen(false);
            onCompleted?.(profile);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}


