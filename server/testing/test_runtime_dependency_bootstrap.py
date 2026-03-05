import unittest
from unittest.mock import patch

from app.bootstrap import runtime_dependency_bootstrap as bootstrap
from app.config import settings
from app.ml.device_profile import DeviceProfile


class RuntimeDependencyBootstrapTests(unittest.TestCase):
    def test_build_required_packages_uses_cuda_bucket_for_nvidia(self):
        profile = DeviceProfile(
            device="cuda",
            backend="torch_cuda",
            gpu_capable=True,
            torch_available=True,
            cuda_available=True,
            mps_available=False,
        )
        with (
            patch.object(settings, "RUNTIME_REQUIREMENTS_CORE", "core-a"),
            patch.object(settings, "RUNTIME_REQUIREMENTS_CPU_EXTRA", "cpu-a"),
            patch.object(settings, "RUNTIME_REQUIREMENTS_CUDA_EXTRA", "cuda-a"),
            patch.object(settings, "RUNTIME_REQUIREMENTS_MPS_EXTRA", "mps-a"),
            patch.object(settings, "RUNTIME_REQUIREMENTS_GPU_EXTRA", "legacy-gpu-a"),
        ):
            required = bootstrap._build_required_packages(profile)

        self.assertEqual(required, ["core-a", "cuda-a", "legacy-gpu-a"])

    def test_build_required_packages_uses_cpu_fallback_for_mps_without_mps_extra(self):
        profile = DeviceProfile(
            device="mps",
            backend="torch_mps",
            gpu_capable=True,
            torch_available=True,
            cuda_available=False,
            mps_available=True,
        )
        with (
            patch.object(settings, "RUNTIME_REQUIREMENTS_CORE", "core-a"),
            patch.object(settings, "RUNTIME_REQUIREMENTS_CPU_EXTRA", "cpu-a,cpu-b"),
            patch.object(settings, "RUNTIME_REQUIREMENTS_CUDA_EXTRA", "cuda-a"),
            patch.object(settings, "RUNTIME_REQUIREMENTS_MPS_EXTRA", ""),
            patch.object(settings, "RUNTIME_REQUIREMENTS_GPU_EXTRA", "legacy-gpu-a"),
        ):
            required = bootstrap._build_required_packages(profile)

        self.assertEqual(required, ["core-a", "cpu-a", "cpu-b"])

    def test_requirement_version_mismatch_returns_false(self):
        if bootstrap._PackagingRequirement is None:
            self.skipTest("packaging is not available in this environment")

        with patch.object(bootstrap.metadata, "version", return_value="2.0.0"):
            ok = bootstrap._is_package_installed("torch>=2.1.0")
        self.assertFalse(ok)

    def test_extract_requirement_name_handles_specifiers(self):
        name = bootstrap._extract_requirement_name(
            'sentence-transformers>=3.0; platform_system == "Windows"'
        )
        self.assertEqual(name, "sentence-transformers")


if __name__ == "__main__":
    unittest.main()
