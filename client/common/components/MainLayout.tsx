import React, { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, Image, Modal, ScrollView } from "react-native";
import { router, usePathname, Slot } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useQueryClient } from "@tanstack/react-query";
import SafeScreenWrapper from "@/common/components/SafeScreenWrapper";
import Sidebar from "@/common/components/Sidebar";
import { Colors } from "@/common/constants/colors";
import { Spacing, Layout } from "@/common/constants/spacing";
import { useAuth } from "@/modules/auth/hooks/useAuth";
import { useAcademicYearContext } from "@/modules/academics/context/AcademicYearContext";
import { CreateAcademicYearModal } from "@/modules/academics/components/CreateAcademicYearModal";
import { isAdmin } from "@/common/constants/navigation";

export default function MainLayout() {
  const [sidebarVisible, setSidebarVisible] = useState(false);
  const [yearPickerVisible, setYearPickerVisible] = useState(false);
  const [createYearModalVisible, setCreateYearModalVisible] = useState(false);
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const { user, permissions } = useAuth();
  const {
    selectedAcademicYearId,
    setSelectedAcademicYearId,
    academicYears,
    isLoading,
  } = useAcademicYearContext();
  const showYearPicker = isAdmin(permissions);

  const handleProfilePress = () => {
    setSidebarVisible(false);
    if (pathname?.includes("profile")) return;
    router.push("/(protected)/profile");
  };

  const selectedLabel =
    selectedAcademicYearId
      ? academicYears.find((ay) => ay.id === selectedAcademicYearId)?.name ?? "Select"
      : "All Years";

  return (
    <SafeScreenWrapper backgroundColor={Colors.background}>
      <View style={styles.container}>
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity
            style={styles.menuButton}
            onPress={() => setSidebarVisible(true)}
            activeOpacity={0.7}
          >
            <Ionicons name="menu" size={28} color={Colors.text} />
          </TouchableOpacity>

          {/* Global Academic Year Selector - Admin only */}
          {showYearPicker ? (
            <TouchableOpacity
              style={styles.yearSelector}
              onPress={() => setYearPickerVisible(true)}
              activeOpacity={0.7}
            >
              <Ionicons name="school" size={18} color={Colors.textSecondary} />
              <Text style={styles.yearSelectorText} numberOfLines={1}>
                {isLoading ? "..." : selectedLabel}
              </Text>
              <Ionicons name="chevron-down" size={16} color={Colors.textSecondary} />
            </TouchableOpacity>
          ) : (
            <View style={styles.yearSelectorPlaceholder} />
          )}

          <TouchableOpacity
            style={styles.profileButton}
            onPress={handleProfilePress}
            activeOpacity={0.7}
          >
            {user?.profile_picture_url ? (
              <Image
                source={{ uri: user.profile_picture_url }}
                style={styles.profileImage}
              />
            ) : (
              <View style={styles.profilePlaceholder}>
                <Ionicons name="person" size={20} color={Colors.text} />
              </View>
            )}
          </TouchableOpacity>
        </View>

        {/* Main Content */}
        <View
          style={styles.content}
          pointerEvents={sidebarVisible ? "none" : "auto"}
        >
          <Slot />
        </View>

        {/* Sidebar */}
        <Sidebar
          visible={sidebarVisible}
          onClose={() => setSidebarVisible(false)}
          currentRoute={pathname}
        />

        {/* Academic Year Picker Modal - Admin only */}
        {showYearPicker && (
        <Modal visible={yearPickerVisible} transparent animationType="fade">
          <TouchableOpacity
            style={styles.modalOverlay}
            activeOpacity={1}
            onPress={() => setYearPickerVisible(false)}
          >
            <View style={styles.modalContent} onStartShouldSetResponder={() => true}>
              <Text style={styles.modalTitle}>Academic Year</Text>
              <ScrollView style={styles.modalList}>
                <TouchableOpacity
                  style={[styles.modalItem, !selectedAcademicYearId && styles.modalItemActive]}
                  onPress={() => {
                    setSelectedAcademicYearId("");
                    setYearPickerVisible(false);
                  }}
                >
                  <Text style={[styles.modalItemText, !selectedAcademicYearId && styles.modalItemTextActive]}>
                    All Years
                  </Text>
                </TouchableOpacity>
                {academicYears.map((ay) => (
                  <TouchableOpacity
                    key={ay.id}
                    style={[styles.modalItem, selectedAcademicYearId === ay.id && styles.modalItemActive]}
                    onPress={() => {
                      setSelectedAcademicYearId(ay.id);
                      setYearPickerVisible(false);
                    }}
                  >
                    <Text
                      style={[
                        styles.modalItemText,
                        selectedAcademicYearId === ay.id && styles.modalItemTextActive,
                      ]}
                    >
                      {ay.name}
                    </Text>
                  </TouchableOpacity>
                ))}
                <TouchableOpacity
                  style={[styles.modalItem, styles.createYearItem]}
                  onPress={() => {
                    setYearPickerVisible(false);
                    setCreateYearModalVisible(true);
                  }}
                >
                  <Ionicons name="add-circle-outline" size={20} color={Colors.primary} />
                  <Text style={styles.createYearText}>Create new academic year</Text>
                </TouchableOpacity>
              </ScrollView>
            </View>
          </TouchableOpacity>
        </Modal>
        )}

        <CreateAcademicYearModal
          visible={createYearModalVisible}
          onClose={() => setCreateYearModalVisible(false)}
          onSuccess={(created) => {
            queryClient.invalidateQueries({ queryKey: ["academics", "academicYears"] });
            setSelectedAcademicYearId(created.id);
          }}
        />
      </View>
    </SafeScreenWrapper>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    height: Layout.headerHeight,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: Spacing.lg,
    backgroundColor: Colors.background,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  menuButton: {
    padding: Spacing.sm,
  },
  profileButton: {
    padding: Spacing.xs,
  },
  profileImage: {
    width: 36,
    height: 36,
    borderRadius: 18,
  },
  profilePlaceholder: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: Colors.backgroundSecondary,
    alignItems: "center",
    justifyContent: "center",
  },
  content: {
    flex: 1,
    backgroundColor: Colors.background,
  },
  yearSelector: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.xs,
    backgroundColor: Colors.backgroundSecondary,
    borderRadius: Layout.borderRadius.sm,
    borderWidth: 1,
    borderColor: Colors.borderLight,
    maxWidth: 140,
  },
  yearSelectorText: {
    fontSize: 13,
    color: Colors.text,
    marginHorizontal: Spacing.xs,
  },
  yearSelectorPlaceholder: {
    flex: 1,
    maxWidth: 140,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    justifyContent: "center",
    alignItems: "center",
    padding: Spacing.lg,
  },
  modalContent: {
    backgroundColor: Colors.background,
    borderRadius: Layout.borderRadius.md,
    padding: Spacing.lg,
    width: "100%",
    maxWidth: 320,
    maxHeight: "70%",
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: "600",
    color: Colors.text,
    marginBottom: Spacing.md,
  },
  modalList: { maxHeight: 300 },
  modalItem: {
    paddingVertical: Spacing.md,
    paddingHorizontal: Spacing.sm,
  },
  modalItemActive: { backgroundColor: Colors.primary + "20" },
  modalItemText: { fontSize: 16, color: Colors.text },
  modalItemTextActive: { color: Colors.primary, fontWeight: "600" },
  createYearItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.sm,
    borderTopWidth: 1,
    borderTopColor: Colors.borderLight,
    marginTop: Spacing.xs,
  },
  createYearText: { fontSize: 16, color: Colors.primary, fontWeight: "500" },
});
