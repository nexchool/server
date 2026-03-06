import { useEffect } from "react";
import { useRouter } from "expo-router";
import { useAuth } from "@/modules/auth/hooks/useAuth";
import MainLayout from "@/common/components/MainLayout";
import { AcademicYearProvider } from "@/modules/academics/context/AcademicYearContext";

export default function ProtectedLayout() {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;

    // Redirect to login if not authenticated
    if (!isAuthenticated) {
      router.replace("/(auth)/login");
    }
  }, [isAuthenticated, isLoading, router]);

  if (isLoading || !isAuthenticated) {
    return null;
  }

  return (
    <AcademicYearProvider>
      <MainLayout />
    </AcademicYearProvider>
  );
}
