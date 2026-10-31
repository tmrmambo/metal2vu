# 23 `MTLDevice` / `MTLDeviceSPI` 的逐方法处置表

文档版本：1.0（**本文由 `tools/ci/gen_device_spi_table.py` 生成，不要手改**）
数据来源：`ci-evidence\objc-dump\objc-dump.json`（schema `metal2vu/objc-runtime-dump/1`）
采集平台：macOS 26.6.1 / 25G76 的 `macos-26-intel` 运行器，见 `91-RUNTIME-EVIDENCE.md`
证据等级：**`TESTED(25G76)`**（运行期 `class_copyMethodList` 与 `protocol_copyMethodDescriptionList` 直接读出，不是静态推断）
上级文档：`00-OVERVIEW.md`　配套：`20-OBJC-DEVICE.md`、`21-OBJC-OBJECT-FAMILY.md`、`42-RUNTIME-MAPPING.md`

## 0. 本文补的是什么

`21-OBJC-OBJECT-FAMILY.md` 第 8.2 节明说「`MTLDeviceSPI` 的 507 条不逐条抄进本文」，所以在本文之前，那 507 条只有分类普查与 28 条交集，**没有逐条处置**。实现者照着它无法回答「这一条我要不要写」。

本文给出逐条答案，而且答案是**从运行期转储机械推出的**，不是人工判断。

### 0.1 判定规则

转储给了三个类的完整 IMP 集合（`TESTED(25G76)`）：

| 类 | IMP 数 | 角色 |
|---|---:|---|
| `_MTLDevice` | 702 | 基类 |
| `MTLIOAccelDevice` | 89 | 家族节点（本项目的 Device 继承它） |
| `AppleParavirtDevice` | 71 | 参考实现 |

「必须覆写 vs 可以继承」（`21` 第 10 节）就是这三个集合的布尔组合：

| 基类有 | APV 覆写 | 处置 | 理由 |
|---|---|---|---|
| ✅ | ✅ | **必须覆写** | 基类有答案但 APV 覆写了 —— 说明基类答案对半虚拟化设备不成立 |
| ✅ | ❌ | **继承** | 参考实现都不覆写，我们也不用 |
| ❌ | ✅ | **必须实现** | 没有可继承的答案 |
| ❌ | ❌ | required 则**待定**，optional 则**可不实现** | 四格里唯一需要人工的一格 |

**第三格（必须实现）与第一格（必须覆写）合起来就是第一版的工作量下界。**

### 0.2 一条重要的读法限制

「继承」不等于「不用管」。它的准确含义是**第一版不用写这一条**，因为 `MTLIOAccelDevice` 或 `_MTLDevice` 的实现会被调到。但那些实现可能依赖本项目没有提供的东西（`20` 第 8 节逐条分析了 resource 层的 `init*` 全部真打内核）。所以「继承」的行必须在 `20`/`21` 的继承分析里交叉验证过才能真的放手。

## 1. 总计

协议声明合计 **624** 条不同 selector（`MTLDevice` 与 `MTLDeviceSPI` 重复声明 22 条，只属 `MTLDeviceSPI` 的 485 条）。

| 处置 | 条数 | 占比 |
|---|---:|---:|
| 继承基类 | 507 | 81.2% |
| 必须实现 | 29 | 4.6% |
| 可不实现(optional) | 28 | 4.5% |
| 待定(required) | 23 | 3.7% |
| 必须覆写 | 20 | 3.2% |
| 继承家族 | 17 | 2.7% |

**第一版必须自己写的是 49 条**（必须覆写 20 + 必须实现 29）。

### 1.1 按语义分组

| 分组 | 条数 |
|---|---:|
| 能力查询 | 271 |
| 工厂（new*，返回 +1） | 140 |
| limits | 67 |
| 其它 | 59 |
| 资源 | 21 |
| 尺寸与对齐查询 | 17 |
| 着色器与管线 | 17 |
| setter | 11 |
| 计数与采样 | 10 |
| 标识与调试 | 5 |
| 私有（下划线前缀） | 5 |
| 生命周期与同步 | 1 |

## 2. 必须自己写的（逐条）

### 2.1 必须覆写（20 条）

| selector | 返回 | 参数 | 分组 | 协议 |
|---|---|---|---|---|
| `llvmVersion` | `int` | — | 其它 | MTLDeviceSPI |
| `newCommandQueueWithDescriptor:` | `id` | id | 工厂（new*，返回 +1） | MTLDevice+MTLDeviceSPI |
| `newRenderPipelineStateWithTileDescriptor:options:completionHandler:` | `void` | id, ulong long, id, unknown/block | 工厂（new*，返回 +1） | MTLDevice |
| `newRenderPipelineStateWithTileDescriptor:options:reflection:error:` | `id` | id, ulong long, id*, id* | 工厂（new*，返回 +1） | MTLDevice |
| `newSharedTextureWithDescriptor:` | `id` | id | 工厂（new*，返回 +1） | MTLDevice |
| `newSharedTextureWithHandle:` | `id` | id | 工厂（new*，返回 +1） | MTLDevice |
| `familyName` | `id` | — | 标识与调试 | MTLDeviceSPI |
| `productName` | `id` | — | 标识与调试 | MTLDeviceSPI |
| `vendorName` | `id` | — | 标识与调试 | MTLDeviceSPI |
| `areProgrammableSamplePositionsSupported` | `char/BOOL` | — | 能力查询 | MTLDevice |
| `isMagicMipmapSupported` | `char/BOOL` | — | 能力查询 | MTLDeviceSPI |
| `supportsArgumentBuffers` | `char/BOOL` | — | 能力查询 | MTLDeviceSPI |
| `supportsBinaryArchives` | `char/BOOL` | — | 能力查询 | MTLDeviceSPI |
| `supportsDynamicLibraries` | `char/BOOL` | — | 能力查询 | MTLDevice+MTLDeviceSPI |
| `supportsFunctionPointers` | `char/BOOL` | — | 能力查询 | MTLDevice+MTLDeviceSPI |
| `supportsFunctionPointersFromRender` | `char/BOOL` | — | 能力查询 | MTLDevice+MTLDeviceSPI |
| `supportsRenderDynamicLibraries` | `char/BOOL` | — | 能力查询 | MTLDevice+MTLDeviceSPI |
| `supportsResourceHeaps` | `char/BOOL` | — | 能力查询 | MTLDeviceSPI |
| `supportsSharedTextureHandles` | `char/BOOL` | — | 能力查询 | MTLDeviceSPI |
| `supportsStatefulDynamicLibraries` | `char/BOOL` | — | 能力查询 | MTLDeviceSPI |

### 2.2 必须实现（29 条）

| selector | 返回 | 参数 | 分组 | 协议 |
|---|---|---|---|---|
| `maxThreadgroupMemoryLength` | `ulong long` | — | limits | MTLDevice |
| `maxThreadsPerThreadgroup` | `struct anon` | — | limits | MTLDevice |
| `setMetalAssertionsEnabled:` | `void` | char/BOOL | setter | MTLDeviceSPI |
| `doubleFPConfig` | `ulong long` | — | 其它 | MTLDeviceSPI |
| `featureProfile` | `ulong long` | — | 其它 | MTLDeviceSPI |
| `halfFPConfig` | `ulong long` | — | 其它 | MTLDeviceSPI |
| `metalAssertionsEnabled` | `char/BOOL` | — | 其它 | MTLDeviceSPI |
| `singleFPConfig` | `ulong long` | — | 其它 | MTLDeviceSPI |
| `newBufferWithBytes:length:options:` | `id` | void*, ulong long, ulong long | 工厂（new*，返回 +1） | MTLDevice |
| `newBufferWithBytesNoCopy:length:options:deallocator:` | `id` | void*, ulong long, ulong long, id, unknown/block | 工厂（new*，返回 +1） | MTLDevice |
| `newBufferWithLength:options:` | `id` | ulong long, ulong long | 工厂（new*，返回 +1） | MTLDevice |
| `newDepthStencilStateWithDescriptor:` | `id` | id | 工厂（new*，返回 +1） | MTLDevice |
| `newFence` | `id` | — | 工厂（new*，返回 +1） | MTLDevice |
| `newHeapWithDescriptor:` | `id` | id | 工厂（new*，返回 +1） | MTLDevice |
| `newIndirectCommandBufferWithDescriptor:maxCount:options:` | `id` | id, ulong long, ulong long | 工厂（new*，返回 +1） | MTLDeviceSPI |
| `newIndirectComputeCommandEncoderWithBuffer:` | `id` | id | 工厂（new*，返回 +1） | MTLDeviceSPI |
| `newIndirectRenderCommandEncoderWithBuffer:` | `id` | id | 工厂（new*，返回 +1） | MTLDeviceSPI |
| `newSamplerStateWithDescriptor:` | `id` | id | 工厂（new*，返回 +1） | MTLDevice |
| `newTextureWithDescriptor:` | `id` | id | 工厂（new*，返回 +1） | MTLDevice |
| `newTextureWithDescriptor:iosurface:plane:` | `id` | id, struct __IOSurface*, ulong long | 工厂（new*，返回 +1） | MTLDevice+MTLDeviceSPI |
| `newVisibleFunctionTableWithDescriptor:` | `id` | id | 工厂（new*，返回 +1） | MTLDeviceSPI |
| `isDepth24Stencil8PixelFormatSupported` | `char/BOOL` | — | 能力查询 | MTLDevice |
| `supportsSampleCount:` | `char/BOOL` | ulong long | 能力查询 | MTLDeviceSPI |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:` | `struct anon` | ulong long, ulong long, ulong long | 计数与采样 | MTLDevice |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:sparsePageSize:` | `struct anon` | ulong long, ulong long, ulong long, long long | 计数与采样 | MTLDevice |
| `copyIOSurfaceSharedTextureProperties:` *(opt)* | `id` | id | 资源 | MTLDeviceSPI |
| `heapBufferSizeAndAlignWithLength:options:` | `struct anon` | ulong long, ulong long | 资源 | MTLDevice |
| `heapTextureSizeAndAlignWithDescriptor:` | `struct anon` | id | 资源 | MTLDevice |
| `minimumTextureBufferAlignmentForPixelFormat:` | `ulong long` | ulong long | 资源 | MTLDevice |

## 3. 待定：协议 required 但三个类都没 IMP

**23 条。这一格是本表唯一需要人工的部分。**

`required` 却连参考实现都不答，有三种可能，必须逐条区分：

1. Metal.framework 的基类在**更上层**答了（`NSObject` 或 category），转储没覆盖到；
2. 它在实践中永不被调用（协议声明是历史包袱）；
3. **它确实需要我们答，而 APV 走的是另一条路绕开了它。**

第 3 类是风险所在。处置：查 `42-RUNTIME-MAPPING.md` 第 5.20 节的落点，有落点的照表转发；没有的进 `42` 第 7 节的新 gap 清单。

| selector | 返回 | 参数 | 分组 |
|---|---|---|---|
| `maxBufferLength` | `ulong long` | — | limits |
| `maxTransferRate` | `ulong long` | — | limits |
| `location` | `ulong long` | — | 其它 |
| `locationNumber` | `ulong long` | — | 其它 |
| `peerGroupID` | `ulong long` | — | 其它 |
| `peerIndex` | `uint` | — | 其它 |
| `registryID` | `ulong long` | — | 其它 |
| `supportPriorityBand` | `char/BOOL` | — | 其它 |
| `currentAllocatedSize` | `ulong long` | — | 尺寸与对齐查询 |
| `dedicatedMemorySize` | `ulong long` | — | 尺寸与对齐查询 |
| `peerCount` | `uint` | — | 尺寸与对齐查询 |
| `recommendedMaxWorkingSetSize` | `ulong long` | — | 尺寸与对齐查询 |
| `sharedMemorySize` | `ulong long` | — | 尺寸与对齐查询 |
| `newIndirectArgumentBufferLayoutWithStructType:` | `id` | id | 工厂（new*，返回 +1） |
| `newIndirectCommandBufferWithDescriptor:maxCommandCount:options:` | `id` | id, ulong long, ulong long | 工厂（new*，返回 +1） |
| `newIntersectionFunctionTableWithDescriptor:` | `id` | id | 工厂（new*，返回 +1） |
| `newTiledTextureWithBytesNoCopy:length:deallocator:descriptor:offset:bytesPerRow:` | `id` | void*, ulong long, id, unknown/block, id, ulong long, ulong long | 工厂（new*，返回 +1） |
| `newTiledTextureWithBytesNoCopy:length:descriptor:offset:bytesPerRow:` | `id` | void*, ulong long, id, ulong long, ulong long | 工厂（new*，返回 +1） |
| `hasUnifiedMemory` | `char/BOOL` | — | 能力查询 |
| `isHeadless` | `char/BOOL` | — | 能力查询 |
| `isLowPower` | `char/BOOL` | — | 能力查询 |
| `isRemovable` | `char/BOOL` | — | 能力查询 |
| `supportsVertexAmplificationCount:` | `char/BOOL` | ulong long | 能力查询 |

## 4. 可以继承的（分组计数 + 全表）

| 处置 | 分组 | 条数 |
|---|---|---:|
| 继承基类 | 能力查询 | 251 |
| 继承基类 | 工厂（new*，返回 +1） | 87 |
| 继承基类 | limits | 63 |
| 继承基类 | 其它 | 44 |
| 继承基类 | 着色器与管线 | 16 |
| 继承基类 | 资源 | 14 |
| 继承家族 | 工厂（new*，返回 +1） | 13 |
| 继承基类 | 尺寸与对齐查询 | 12 |
| 继承基类 | setter | 9 |
| 继承基类 | 计数与采样 | 5 |
| 继承基类 | 私有（下划线前缀） | 3 |
| 继承基类 | 标识与调试 | 2 |
| 继承家族 | 私有（下划线前缀） | 2 |
| 继承基类 | 生命周期与同步 | 1 |
| 继承家族 | 其它 | 1 |
| 继承家族 | 能力查询 | 1 |

<details>
<summary>全部 524 条</summary>

| selector | 返回 | 处置 |
|---|---|---|
| `maxAccelerationStructureLevels` | `ulong long` | 继承基类 |
| `maxAccelerationStructureTraversalDepth` | `ulong long` | 继承基类 |
| `maxArgumentBufferSamplerCount` | `ulong long` | 继承基类 |
| `maxColorAttachments` | `ulong long` | 继承基类 |
| `maxComputeAttributes` | `ulong long` | 继承基类 |
| `maxComputeBuffers` | `ulong long` | 继承基类 |
| `maxComputeInlineDataSize` | `ulong long` | 继承基类 |
| `maxComputeLocalMemorySizes` | `ulong long` | 继承基类 |
| `maxComputeSamplers` | `ulong long` | 继承基类 |
| `maxComputeTextures` | `ulong long` | 继承基类 |
| `maxComputeThreadgroupMemory` | `ulong long` | 继承基类 |
| `maxComputeThreadgroupMemoryAlignmentBytes` | `ulong long` | 继承基类 |
| `maxConcurrentExecutingCompilationTasks` | `ulong long` | 继承基类 |
| `maxConstantBufferArguments` | `ulong long` | 继承基类 |
| `maxCustomSamplePositions` | `ulong long` | 继承基类 |
| `maxFenceInstances` | `ulong long` | 继承基类 |
| `maxFragmentBuffers` | `ulong long` | 继承基类 |
| `maxFragmentInlineDataSize` | `ulong long` | 继承基类 |
| `maxFragmentSamplers` | `ulong long` | 继承基类 |
| `maxFragmentTextures` | `ulong long` | 继承基类 |
| `maxFramebufferStorageBits` | `ulong long` | 继承基类 |
| `maxFunctionConstantIndices` | `ulong long` | 继承基类 |
| `maxIOCommandsInFlight` | `ulong long` | 继承基类 |
| `maxIndirectBuffers` | `ulong long` | 继承基类 |
| `maxIndirectSamplers` | `ulong long` | 继承基类 |
| `maxIndirectSamplersPerDevice` | `ulong long` | 继承基类 |
| `maxIndirectTextures` | `ulong long` | 继承基类 |
| `maxInterpolants` | `ulong long` | 继承基类 |
| `maxInterpolatedComponents` | `ulong long` | 继承基类 |
| `maxLineWidth` | `float` | 继承基类 |
| `maxPointSize` | `float` | 继承基类 |
| `maxPredicatedNestingDepth` | `ulong long` | 继承基类 |
| `maxRasterizationRateLayerCount` | `ulong long` | 继承基类 |
| `maxTessellationFactor` | `ulong long` | 继承基类 |
| `maxTextureBufferWidth` | `ulong long` | 继承基类 |
| `maxTextureDepth3D` | `ulong long` | 继承基类 |
| `maxTextureDimensionCube` | `ulong long` | 继承基类 |
| `maxTextureHeight2D` | `ulong long` | 继承基类 |
| `maxTextureHeight3D` | `ulong long` | 继承基类 |
| `maxTextureLayers` | `ulong long` | 继承基类 |
| `maxTextureWidth1D` | `ulong long` | 继承基类 |
| `maxTextureWidth2D` | `ulong long` | 继承基类 |
| `maxTextureWidth3D` | `ulong long` | 继承基类 |
| `maxTileBuffers` | `ulong long` | 继承基类 |
| `maxTileInlineDataSize` | `ulong long` | 继承基类 |
| `maxTileSamplers` | `ulong long` | 继承基类 |
| `maxTileTextures` | `ulong long` | 继承基类 |
| `maxTotalComputeThreadsPerThreadgroup` | `ulong long` | 继承基类 |
| `maxVertexAmplificationCount` | `ulong long` | 继承基类 |
| `maxVertexAmplificationFactor` | `ulong long` | 继承基类 |
| `maxVertexAttributes` | `ulong long` | 继承基类 |
| `maxVertexBuffers` | `ulong long` | 继承基类 |
| `maxVertexInlineDataSize` | `ulong long` | 继承基类 |
| `maxVertexSamplers` | `ulong long` | 继承基类 |
| `maxVertexTextures` | `ulong long` | 继承基类 |
| `maxViewportCount` | `ulong long` | 继承基类 |
| `maxVisibilityQueryOffset` | `ulong long` | 继承基类 |
| `minBufferNoCopyAlignmentBytes` | `ulong long` | 继承基类 |
| `minConstantBufferAlignmentBytes` | `ulong long` | 继承基类 |
| `minLinearTextureAlignmentForPixelFormat:` | `ulong long` | 继承基类 |
| `minLinearTextureBaseAddressAlignmentForDescriptor:` | `ulong long` | 继承基类 |
| `minLinearTexturePitchAlignmentForDescriptor:mustMatchExactly:` | `ulong long` | 继承基类 |
| `minTilePixels` | `ulong long` | 继承基类 |
| `setCommandBufferErrorOptions:` | `void` | 继承基类 |
| `setCompilerProcessesCount:` | `char/BOOL` | 继承基类 |
| `setGPUAssertionsEnabled:` | `void` | 继承基类 |
| `setPluginData:` | `void` | 继承基类 |
| `setRawBVHBuilderPtr:` | `void` | 继承基类 |
| `setRequiresLegacyCompilerProcessesCount:` | `void` | 继承基类 |
| `setShaderDebugInfoCaching:` | `void` | 继承基类 |
| `setShouldMaximizeConcurrentCompilation:` | `void` | 继承基类 |
| `setWritableHeapsEnabled:` | `void` | 继承基类 |
| `GPUBVHBuilder` | `id` | 继承基类 |
| `accelerationStructureSizesWithDescriptor:` | `struct anon` | 继承基类 |
| `allowLibrariesFromOtherPlatforms` | `void` | 继承基类 |
| `architecture` | `id` | 继承基类 |
| `commandQueueLimit` | `ulong long` | 继承基类 |
| `compilerPropagatesThreadPriority:` | `void` | 继承基类 |
| `convertSparsePixelRegions:toTileRegions:withTileSize:alignmentMode:numRegions:` | `void` | 继承基类 |
| `convertSparseTileRegions:toPixelRegions:withTileSize:numRegions:` | `void` | 继承基类 |
| `currentPerformanceState` | `long long` | 继承基类 |
| `deserializeCompileTimeStats:addToDictionary:` | `void` | 继承基类 |
| `deserializeInstanceAccelerationStructure:fromBytes:primitiveAccelerationStructures:withDescriptor:` | `void` | 继承基类 |
| `deserializeInstanceAccelerationStructureFromBytes:primitiveAccelerationStructures:withDescriptor:` | `id` | 继承基类 |
| `deserializePrimitiveAccelerationStructure:fromBytes:withDescriptor:` | `void` | 继承基类 |
| `deserializePrimitiveAccelerationStructureFromBytes:withDescriptor:` | `id` | 继承基类 |
| `deviceCreationFlags` | `ulong long` | 继承基类 |
| `deviceOrFeatureProfileSupportsFeatureSet:` | `char/BOOL` | 继承基类 |
| `deviceSupportsFeatureSet:` | `char/BOOL` | 继承基类 |
| `featureQueries` | `id` | 继承基类 |
| `getBVHBuilderLock` | `struct os_unfair_lock_s*` | 继承基类 |
| `getCompilerConnectionManager:` | `struct MTLCompilerConnectionManager*` | 继承基类 |
| `getMostCompatibleArchitecture:` | `id` | 继承基类 |
| `getRawBVHBuilderPtr` | `id` | 继承基类 |
| `getShaderCacheKeys` | `void*` | 继承基类 |
| `latestSupportedGenericBVHVersion` | `ulong long` | 继承基类 |
| `limits` | `struct anon*` | 继承基类 |
| `loadDynamicLibrariesForComputeDescriptor:error:` | `id` | 继承基类 |
| `loadDynamicLibrariesForComputeDescriptor:options:error:` | `id` | 继承基类 |
| `maximumComputeSubstreams` | `uint` | 继承基类 |
| `motionEstimatorCapabilities` | `id` | 继承基类 |
| `pluginData` | `id` | 继承基类 |
| `queryTimestampFrequency` | `ulong long` | 继承基类 |
| `requiresBFloat16Emulation` | `char/BOOL` | 继承基类 |
| `requiresMeshShaderEmulation` | `char/BOOL` | 继承基类 |
| `requiresRaytracingEmulation` | `char/BOOL` | 继承基类 |
| `serializeStructType:` | `id` | 继承基类 |
| `serializeStructType:version:` | `id` | 继承基类 |
| `shaderDebugInfoCaching` | `char/BOOL` | 继承基类 |
| `sparseTileSizeInBytesForSparsePageSize:` | `ulong long` | 继承基类 |
| `targetDeviceArchitecture` | `id` | 继承基类 |
| `targetDeviceInfo` | `struct MTLTargetDeviceArch*` | 继承基类 |
| `tensorSizeAndAlignWithDescriptor:` | `struct anon` | 继承基类 |
| `threadsPerCompilerProcess` | `int` | 继承基类 |
| `unloadShaderCaches` | `void` | 继承基类 |
| `writeMeshShaderEmulatorDataStructureHeader:meshShaderPSO:scalingFactor:` | `void` | 继承基类 |
| `currentCommandQueueCount` | `ulong long` | 继承基类 |
| `defaultCompilerProcessesCount` | `int` | 继承基类 |
| `deviceLinearReadOnlyTextureAlignmentBytes` | `ulong long` | 继承基类 |
| `deviceLinearTextureAlignmentBytes` | `ulong long` | 继承基类 |
| `iosurfaceReadOnlyTextureAlignmentBytes` | `ulong long` | 继承基类 |
| `iosurfaceTextureAlignmentBytes` | `ulong long` | 继承基类 |
| `linearTextureAlignmentBytes` | `ulong long` | 继承基类 |
| `linearTextureArrayAlignmentBytes` | `ulong long` | 继承基类 |
| `maximumCompilerProcessesCount` | `int` | 继承基类 |
| `maximumConcurrentCompilationTaskCount` | `ulong long` | 继承基类 |
| `requiresLegacyCompilerProcessesCount` | `char/BOOL` | 继承基类 |
| `sparseTileSizeInBytes` | `ulong long` | 继承基类 |
| `newAccelerationStructureWithDescriptor:` | `id` | 继承基类 |
| `newArchiveWithURL:error:` | `id` | 继承基类 |
| `newArgumentEncoderWithArguments:` | `id` | 继承基类 |
| `newArgumentEncoderWithBufferBinding:` | `id` | 继承基类 |
| `newArgumentTableWithDescriptor:error:` | `id` | 继承基类 |
| `newBinaryArchiveWithDescriptor:error:` | `id` | 继承基类 |
| `newBinaryLibraryWithOptions:url:error:` | `id` | 继承基类 |
| `newBufferWithLength:options:placementSparsePageSize:` | `id` | 继承基类 |
| `newCommandAllocator` | `id` | 继承基类 |
| `newCommandAllocatorWithDescriptor:error:` | `id` | 继承基类 |
| `newCommandBuffer` | `id` | 继承基类 |
| `newCommandQueue` | `id` | 继承基类 |
| `newCommandQueueWithMaxCommandBufferCount:` | `id` | 继承基类 |
| `newCompilerWithDescriptor:error:` | `id` | 继承基类 |
| `newComputePipelineDescriptorWithSerializedData:deserializationContext:` | `id` | 继承基类 |
| `newComputePipelineStateWithDescriptor:completionHandler:` | `void` | 继承基类 |
| `newComputePipelineStateWithDescriptor:error:` | `id` | 继承基类 |
| `newComputePipelineStateWithDescriptor:options:completionHandler:` | `void` | 继承基类 |
| `newComputePipelineStateWithDescriptor:options:reflection:error:` | `id` | 继承基类 |
| `newComputePipelineStateWithFunction:completionHandler:` | `void` | 继承基类 |
| `newComputePipelineStateWithFunction:error:` | `id` | 继承基类 |
| `newComputePipelineStateWithFunction:options:completionHandler:` | `void` | 继承基类 |
| `newComputePipelineStateWithFunction:options:reflection:error:` | `id` | 继承基类 |
| `newComputePipelineStateWithImageFilterFunctionsSPI:imageFilterFunctionInfo:error:` | `id` | 继承基类 |
| `newCounterHeapWithDescriptor:error:` | `id` | 继承基类 |
| `newCounterSampleBufferWithDescriptor:error:` | `id` | 继承基类 |
| `newDagStringWithGraphs:` | `id` | 继承基类 |
| `newDefaultLibrary` | `id` | 继承基类 |
| `newDefaultLibraryWithBundle:error:` | `id` | 继承基类 |
| `newDynamicLibrary:computeDescriptor:error:` | `id` | 继承基类 |
| `newDynamicLibrary:error:` | `id` | 继承基类 |
| `newDynamicLibraryFromURL:error:` | `id` | 继承基类 |
| `newDynamicLibraryWithDescriptor:error:` | `id` | 继承基类 |
| `newDynamicLibraryWithURL:error:` | `id` | 继承基类 |
| `newDynamicLibraryWithURL:options:error:` | `id` | 继承基类 |
| `newFunctionWithGLCoreIR:functionType:` | `id` | 继承基类 |
| `newFunctionWithGLCoreIR:inputsDescription:functionType:` | `id` | 继承基类 |
| `newFunctionWithGLESIR:functionType:` | `id` | 继承基类 |
| `newFunctionWithGLESIR:inputsDescription:functionType:` | `id` | 继承基类 |
| `newFunctionWithGLIR:functionType:` | `id` | 继承基类 |
| `newFunctionWithGLIR:inputsDescription:functionType:` | `id` | 继承基类 |
| `newLateEvalEvent` | `id` | 继承基类 |
| `newLibraryWithCIFilters:imageFilterFunctionInfo:error:` | `id` | 继承基类 |
| `newLibraryWithDAG:functions:error:` | `id` | 继承基类 |
| `newLibraryWithData:error:` | `id` | 继承基类 |
| `newLibraryWithDescriptor:completionHandler:` | `void` | 继承基类 |
| `newLibraryWithDescriptor:error:` | `id` | 继承基类 |
| `newLibraryWithDescriptorSPI:error:` | `id` | 继承基类 |
| `newLibraryWithFile:error:` | `id` | 继承基类 |
| `newLibraryWithImageFilterFunctionsSPI:imageFilterFunctionInfo:error:` | `id` | 继承基类 |
| `newLibraryWithMPSGraphPackageURL:name:error:` | `id` | 继承基类 |
| `newLibraryWithSource:options:completionHandler:` | `void` | 继承基类 |
| `newLibraryWithSource:options:error:` | `id` | 继承基类 |
| `newLibraryWithStitchedDescriptor:completionHandler:` | `void` | 继承基类 |
| `newLibraryWithStitchedDescriptor:error:` | `id` | 继承基类 |
| `newLibraryWithStitchedDescriptorSPI:error:` | `id` | 继承基类 |
| `newLibraryWithURL:error:` | `id` | 继承基类 |
| `newLogStateWithDescriptor:error:` | `id` | 继承基类 |
| `newMTL4CommandQueue` | `id` | 继承基类 |
| `newMTL4CommandQueueWithDescriptor:error:` | `id` | 继承基类 |
| `newPerformanceStateAssertion:error:` | `id` | 继承基类 |
| `newPipelineDataSetSerializerWithDescriptor:` | `id` | 继承基类 |
| `newPipelineLibraryWithFilePath:error:` | `id` | 继承基类 |
| `newPrecompiledComputePipelineStateWithDescriptor:options:pipelineCache:completionHandler:` | `void` | 继承基类 |
| `newPrecompiledRenderPipelineStateWithDescriptor:options:pipelineCache:completionHandler:` | `void` | 继承基类 |
| `newProfileWithExecutionSize:` | `id` | 继承基类 |
| `newRasterizationRateMapWithDescriptor:` | `id` | 继承基类 |
| `newRenderPipelineDescriptorWithSerializedData:deserializationContext:` | `id` | 继承基类 |
| `newRenderPipelineStateWithDescriptor:completionHandler:` | `void` | 继承基类 |
| `newRenderPipelineStateWithDescriptor:error:` | `id` | 继承基类 |
| `newRenderPipelineStateWithDescriptor:options:completionHandler:` | `void` | 继承基类 |
| `newRenderPipelineStateWithDescriptor:options:reflection:error:` | `id` | 继承基类 |
| `newRenderPipelineStateWithMeshDescriptor:completionHandler:` | `void` | 继承基类 |
| `newRenderPipelineStateWithMeshDescriptor:error:` | `id` | 继承基类 |
| `newRenderPipelineStateWithMeshDescriptor:options:completionHandler:` | `void` | 继承基类 |
| `newRenderPipelineStateWithMeshDescriptor:options:reflection:error:` | `id` | 继承基类 |
| `newResidencySetWithDescriptor:error:` | `id` | 继承基类 |
| `newSharedEvent` | `id` | 继承基类 |
| `newSharedEventWithHandle:` | `id` | 继承基类 |
| `newSharedEventWithMachPort:` | `id` | 继承基类 |
| `newSharedEventWithOptions:` | `id` | 继承基类 |
| `newStructTypeWithSerializedData:` | `id` | 继承基类 |
| `newTensorWithDescriptor:error:` | `id` | 继承基类 |
| `newTextureViewPoolWithDescriptor:error:` | `id` | 继承基类 |
| `newTextureWithDescriptor:iosurface:plane:slice:` | `id` | 继承基类 |
| `newTextureWithSurface:buffer:` | `id` | 继承基类 |
| `newTileRenderPipelineDescriptorWithSerializedData:deserializationContext:` | `id` | 继承基类 |
| `name` | `id` | 继承基类 |
| `startCollectingPipelineDescriptorsUsingPrefixForNames:` | `void` | 继承基类 |
| `endCollectingPipelineDescriptors` | `id` | 继承基类 |
| `compileVisibleFunction:withDescriptor:completionHandler:` | `void` | 继承基类 |
| `compileVisibleFunction:withDescriptor:destinationBinaryArchive:error:` | `void` | 继承基类 |
| `compileVisibleFunction:withDescriptor:error:` | `void` | 继承基类 |
| `functionHandleWithBinaryFunction:` | `id` | 继承基类 |
| `functionHandleWithFunction:` | `id` | 继承基类 |
| `libraryCacheStats` | `struct anon` | 继承基类 |
| `loadDynamicLibrariesForFunction:insertLibraries:error:` | `id` | 继承基类 |
| `loadDynamicLibrariesForFunction:insertLibraries:options:error:` | `id` | 继承基类 |
| `pipelineCacheStats` | `struct anon` | 继承基类 |
| `serializeComputePipelineDescriptor:` | `id` | 继承基类 |
| `serializeRenderPipelineDescriptor:` | `id` | 继承基类 |
| `serializeTileRenderPipelineDescriptor:` | `id` | 继承基类 |
| `startCollectingPipelineDescriptors` | `void` | 继承基类 |
| `validateDynamicLibrary:state:error:` | `char/BOOL` | 继承基类 |
| `validateDynamicLibraryDescriptor:error:` | `char/BOOL` | 继承基类 |
| `validateDynamicLibraryURL:error:` | `char/BOOL` | 继承基类 |
| `_registerInterestNotification` | `char/BOOL` | 继承基类 |
| `_removeRequested` | `void` | 继承基类 |
| `_wasRemoved` | `void` | 继承基类 |
| `areBarycentricCoordsSupported` | `char/BOOL` | 继承基类 |
| `areGPUAssertionsEnabled` | `char/BOOL` | 继承基类 |
| `areRasterOrderGroupsSupported` | `char/BOOL` | 继承基类 |
| `areWritableHeapsEnabled` | `char/BOOL` | 继承基类 |
| `isASTCPixelFormatsSupported` | `char/BOOL` | 继承基类 |
| `isAnisoSampleFixSupported` | `char/BOOL` | 继承基类 |
| `isBCTextureCompressionSupported` | `char/BOOL` | 继承基类 |
| `isClampToHalfBorderSupported` | `char/BOOL` | 继承基类 |
| `isCompatibleWithAccelerationStructure:` | `char/BOOL` | 继承基类 |
| `isCustomBorderColorSupported` | `char/BOOL` | 继承基类 |
| `isFixedLinePointFillDepthGradientSupported` | `char/BOOL` | 继承基类 |
| `isFloat32FilteringSupported` | `char/BOOL` | 继承基类 |
| `isFramebufferReadSupported` | `char/BOOL` | 继承基类 |
| `isLargeMRTSupported` | `char/BOOL` | 继承基类 |
| `isMsaa32bSupported` | `char/BOOL` | 继承基类 |
| `isPlacementHeapSupported` | `char/BOOL` | 继承基类 |
| `isQuadDataSharingSupported` | `char/BOOL` | 继承基类 |
| `isRGB10A2GammaSupported` | `char/BOOL` | 继承基类 |
| `isRTZRoundingSupported` | `char/BOOL` | 继承基类 |
| `isVendorSliceCompatibleWithDeploymentTarget:platform:sdkVersion:compilerPluginVersion:` | `char/BOOL` | 继承基类 |
| `shouldMaximizeConcurrentCompilation` | `char/BOOL` | 继承基类 |
| `supports2DLinearTexArraySPI` | `char/BOOL` | 继承基类 |
| `supports32BitFloatFiltering` | `char/BOOL` | 继承基类 |
| `supports32BitMSAA` | `char/BOOL` | 继承基类 |
| `supports32bpcMSAATextures` | `char/BOOL` | 继承基类 |
| `supports3DASTCTextures` | `char/BOOL` | 继承基类 |
| `supports3DBCTextures` | `char/BOOL` | 继承基类 |
| `supportsAIRNTBinaryArchiveFunctionPointers` | `char/BOOL` | 继承基类 |
| `supportsAIRNTBinaryArchiveSpecializedFunctions` | `char/BOOL` | 继承基类 |
| `supportsAIRNTBinaryArchiveStitchedFunctions` | `char/BOOL` | 继承基类 |
| `supportsASTCHDRTextureCompression` | `char/BOOL` | 继承基类 |
| `supportsASTCTextureCompression` | `char/BOOL` | 继承基类 |
| `supportsAlphaYUVFormats` | `char/BOOL` | 继承基类 |
| `supportsAnisoSampleFix` | `char/BOOL` | 继承基类 |
| `supportsArgumentBuffersTier2` | `char/BOOL` | 继承基类 |
| `supportsArrayOfSamplers` | `char/BOOL` | 继承基类 |
| `supportsArrayOfTextures` | `char/BOOL` | 继承基类 |
| `supportsAtomicFloat` | `char/BOOL` | 继承基类 |
| `supportsAtomicUlongVoidMinMax` | `char/BOOL` | 继承基类 |
| `supportsAtomicWaitNotify` | `char/BOOL` | 继承基类 |
| `supportsBCTextureCompression` | `char/BOOL` | 继承基类 |
| `supportsBGR10A2` | `char/BOOL` | 继承基类 |
| `supportsBaseVertexInstanceDrawing` | `char/BOOL` | 继承基类 |
| `supportsBfloat16Buffers` | `char/BOOL` | 继承基类 |
| `supportsBfloat16Format` | `char/BOOL` | 继承基类 |
| `supportsBinaryLibraries` | `char/BOOL` | 继承基类 |
| `supportsBlackOrWhiteSamplerBorderColors` | `char/BOOL` | 继承基类 |
| `supportsBufferBoundsChecking` | `char/BOOL` | 继承基类 |
| `supportsBufferPrefetchStatistics` | `char/BOOL` | 继承基类 |
| `supportsBufferWithAddressRanges` | `char/BOOL` | 继承基类 |
| `supportsBufferWithIOSurface` | `char/BOOL` | 继承基类 |
| `supportsBufferlessClientStorageTexture` | `char/BOOL` | 继承基类 |
| `supportsCMPIndirectCommandBuffers` | `char/BOOL` | 继承基类 |
| `supportsColorSpaceConversionMatrixSelection` | `char/BOOL` | 继承基类 |
| `supportsCombinedMSAAStoreAndResolveAction` | `char/BOOL` | 继承基类 |
| `supportsCommandBufferJump` | `char/BOOL` | 继承基类 |
| `supportsCommandQueueBarriers` | `char/BOOL` | 继承基类 |
| `supportsCompressedTextureViewSPI` | `char/BOOL` | 继承基类 |
| `supportsComputeCompressedTextureWrite` | `char/BOOL` | 继承基类 |
| `supportsComputeMemoryBarrier` | `char/BOOL` | 继承基类 |
| `supportsConcurrentComputeDispatch` | `char/BOOL` | 继承基类 |
| `supportsConditionalLoadStore` | `char/BOOL` | 继承基类 |
| `supportsConditionalTileDispatch` | `char/BOOL` | 继承基类 |
| `supportsCounterSampling:` | `char/BOOL` | 继承基类 |
| `supportsCountingOcclusionQuery` | `char/BOOL` | 继承基类 |
| `supportsCustomBorderColor` | `char/BOOL` | 继承基类 |
| `supportsDeadlineProfile` | `char/BOOL` | 继承基类 |
| `supportsDepthBoundsTesting` | `char/BOOL` | 继承基类 |
| `supportsDepthClipMode` | `char/BOOL` | 继承基类 |
| `supportsDepthClipModeClampExtended` | `char/BOOL` | 继承基类 |
| `supportsDeviceCoherency` | `char/BOOL` | 继承基类 |
| `supportsDevicePartitioning` | `char/BOOL` | 继承基类 |
| `supportsDynamicAttributeStride` | `char/BOOL` | 继承基类 |
| `supportsDynamicControlPointCount` | `char/BOOL` | 继承基类 |
| `supportsExplicitVisibilityGroups` | `char/BOOL` | 继承基类 |
| `supportsExtendedIndirectRenderCommand` | `char/BOOL` | 继承基类 |
| `supportsExtendedSamplerLODBiasRange` | `char/BOOL` | 继承基类 |
| `supportsExtendedVertexFormats` | `char/BOOL` | 继承基类 |
| `supportsExtendedXR10Formats` | `char/BOOL` | 继承基类 |
| `supportsExtendedYUVFormats` | `char/BOOL` | 继承基类 |
| `supportsFP32TessFactors` | `char/BOOL` | 继承基类 |
| `supportsFP8` | `char/BOOL` | 继承基类 |
| `supportsFamily:` | `char/BOOL` | 继承基类 |
| `supportsFastMathInfNaNPropagation` | `char/BOOL` | 继承基类 |
| `supportsFeatureSet:` | `char/BOOL` | 继承基类 |
| `supportsFillTexture` | `char/BOOL` | 继承基类 |
| `supportsFixedLinePointFillDepthGradient` | `char/BOOL` | 继承基类 |
| `supportsFloat16BCubicFiltering` | `char/BOOL` | 继承基类 |
| `supportsFloat16InfNanFiltering` | `char/BOOL` | 继承基类 |
| `supportsForceSeamsOnCubemaps` | `char/BOOL` | 继承基类 |
| `supportsForkJoin` | `char/BOOL` | 继承基类 |
| `supportsFragmentBufferWrites` | `char/BOOL` | 继承基类 |
| `supportsFragmentOnlyEncoders` | `char/BOOL` | 继承基类 |
| `supportsFunctionPointersFromMesh` | `char/BOOL` | 继承基类 |
| `supportsGFXIndirectCommandBuffers` | `char/BOOL` | 继承基类 |
| `supportsGPUStatistics` | `char/BOOL` | 继承基类 |
| `supportsGlobalVariableBindingInDylibs` | `char/BOOL` | 继承基类 |
| `supportsGlobalVariableBindings` | `char/BOOL` | 继承基类 |
| `supportsGlobalVariableRelocation` | `char/BOOL` | 继承基类 |
| `supportsGlobalVariableRelocationCompute` | `char/BOOL` | 继承基类 |
| `supportsGlobalVariableRelocationRender` | `char/BOOL` | 继承基类 |
| `supportsHeapAccelerationStructureAllocation` | `char/BOOL` | 继承基类 |
| `supportsHeapWithAddressRanges` | `char/BOOL` | 继承基类 |
| `supportsIABHashForTools` | `char/BOOL` | 继承基类 |
| `supportsImageBlockSampleCoverageControl` | `char/BOOL` | 继承基类 |
| `supportsImageBlocks` | `char/BOOL` | 继承基类 |
| `supportsIndirectDrawAndDispatch` | `char/BOOL` | 继承基类 |
| `supportsIndirectStageInRegion` | `char/BOOL` | 继承基类 |
| `supportsIndirectTessellation` | `char/BOOL` | 继承基类 |
| `supportsIndirectTextures` | `char/BOOL` | 继承基类 |
| `supportsIndirectWritableTextures` | `char/BOOL` | 继承基类 |
| `supportsInt64` | `char/BOOL` | 继承基类 |
| `supportsInterchangeTiled` | `char/BOOL` | 继承基类 |
| `supportsIntersectionFunctionBuffers` | `char/BOOL` | 继承基类 |
| `supportsInvariantVertexPosition` | `char/BOOL` | 继承基类 |
| `supportsLargeFramebufferConfigs` | `char/BOOL` | 继承基类 |
| `supportsLateEvalEvent` | `char/BOOL` | 继承基类 |
| `supportsLayeredRendering` | `char/BOOL` | 继承基类 |
| `supportsLimitedYUVFormats` | `char/BOOL` | 继承基类 |
| `supportsLinearTexture2DArray` | `char/BOOL` | 继承基类 |
| `supportsLinearTextureFromSharedBuffer` | `char/BOOL` | 继承基类 |
| `supportsLossyCompression` | `char/BOOL` | 继承基类 |
| `supportsMSAADepthResolve` | `char/BOOL` | 继承基类 |
| `supportsMSAADepthResolveFilter` | `char/BOOL` | 继承基类 |
| `supportsMSAAStencilResolve` | `char/BOOL` | 继承基类 |
| `supportsMSAAStencilResolveFilter` | `char/BOOL` | 继承基类 |
| `supportsMTL4CommandAllocator` | `char/BOOL` | 继承基类 |
| `supportsMTL4CommandQueue` | `char/BOOL` | 继承基类 |
| `supportsMTL4Compiler` | `char/BOOL` | 继承基类 |
| `supportsMTL4ComputeCommandEncoder` | `char/BOOL` | 继承基类 |
| `supportsMTL4Counters` | `char/BOOL` | 继承基类 |
| `supportsMTL4LateBoundRenderTargets` | `char/BOOL` | 继承基类 |
| `supportsMTL4PSOSpecialization` | `char/BOOL` | 继承基类 |
| `supportsMTL4PlacementSparse` | `char/BOOL` | 继承基类 |
| `supportsMTL4RenderCommandEncoder` | `char/BOOL` | 继承基类 |
| `supportsMTLTextureViewPools` | `char/BOOL` | 继承基类 |
| `supportsMXU` | `char/BOOL` | 继承基类 |
| `supportsMachineLearningCommandEncoders` | `char/BOOL` | 继承基类 |
| `supportsMemoryOrderAtomics` | `char/BOOL` | 继承基类 |
| `supportsMemorylessRenderTargets` | `char/BOOL` | 继承基类 |
| `supportsMeshRenderDynamicLibraries` | `char/BOOL` | 继承基类 |
| `supportsMeshShaders` | `char/BOOL` | 继承基类 |
| `supportsMeshShadersInICB` | `char/BOOL` | 继承基类 |
| `supportsMipLevelsSmallerThanBlockSize` | `char/BOOL` | 继承基类 |
| `supportsMirrorClampToEdgeSamplerMode` | `char/BOOL` | 继承基类 |
| `supportsMutableTier1ArgumentBuffers` | `char/BOOL` | 继承基类 |
| `supportsNativeHardwareFP16` | `char/BOOL` | 继承基类 |
| `supportsNonPrivateDepthStencilTextures` | `char/BOOL` | 继承基类 |
| `supportsNonPrivateMSAATextures` | `char/BOOL` | 继承基类 |
| `supportsNonSquareTileShaders` | `char/BOOL` | 继承基类 |
| `supportsNonUniformThreadgroupSize` | `char/BOOL` | 继承基类 |
| `supportsNonZeroTextureWriteLOD` | `char/BOOL` | 继承基类 |
| `supportsNorm16BCubicFiltering` | `char/BOOL` | 继承基类 |
| `supportsOpenCLTextureWriteSwizzles` | `char/BOOL` | 继承基类 |
| `supportsPacked32TextureBufferWrites` | `char/BOOL` | 继承基类 |
| `supportsPartialRenderMemoryBarrier` | `char/BOOL` | 继承基类 |
| `supportsPerPlaneCompression` | `char/BOOL` | 继承基类 |
| `supportsPerformanceStateAssertion` | `char/BOOL` | 继承基类 |
| `supportsPipelineLibraries` | `char/BOOL` | 继承基类 |
| `supportsPlacementHeaps` | `char/BOOL` | 继承基类 |
| `supportsPlacementSparse` | `char/BOOL` | 继承基类 |
| `supportsPostDepthCoverage` | `char/BOOL` | 继承基类 |
| `supportsPrimitiveMotionBlur` | `char/BOOL` | 继承基类 |
| `supportsPrimitiveRestartOverride` | `char/BOOL` | 继承基类 |
| `supportsPrimitiveType:` | `char/BOOL` | 继承基类 |
| `supportsProgrammableBlending` | `char/BOOL` | 继承基类 |
| `supportsProgrammableSamplePositions` | `char/BOOL` | 继承基类 |
| `supportsPublicXR10Formats` | `char/BOOL` | 继承基类 |
| `supportsPullModelInterpolation` | `char/BOOL` | 继承基类 |
| `supportsQuadGroup` | `char/BOOL` | 继承基类 |
| `supportsQuadReduction` | `char/BOOL` | 继承基类 |
| `supportsQuadShufflesAndBroadcast` | `char/BOOL` | 继承基类 |
| `supportsQueryTextureLOD` | `char/BOOL` | 继承基类 |
| `supportsRGBA10A2Gamma` | `char/BOOL` | 继承基类 |
| `supportsRTZRounding` | `char/BOOL` | 继承基类 |
| `supportsRasterOrderGroups` | `char/BOOL` | 继承基类 |
| `supportsRasterOrderGroupsColorAttachment` | `char/BOOL` | 继承基类 |
| `supportsRasterizationRateMapWithLayerCount:` | `char/BOOL` | 继承基类 |
| `supportsRayTracingAccelerationStructureCPUDeserialization` | `char/BOOL` | 继承基类 |
| `supportsRayTracingBuffersFromTables` | `char/BOOL` | 继承基类 |
| `supportsRayTracingCurves` | `char/BOOL` | 继承基类 |
| `supportsRayTracingDirectIntersectionResultAccess` | `char/BOOL` | 继承基类 |
| `supportsRayTracingExtendedVertexFormats` | `char/BOOL` | 继承基类 |
| `supportsRayTracingGPUTableUpdateBuffers` | `char/BOOL` | 继承基类 |
| `supportsRayTracingICBs` | `char/BOOL` | 继承基类 |
| `supportsRayTracingIndirectInstanceAccelerationStructureBuild` | `char/BOOL` | 继承基类 |
| `supportsRayTracingMatrixLayout` | `char/BOOL` | 继承基类 |
| `supportsRayTracingMultiLevelInstancing` | `char/BOOL` | 继承基类 |
| `supportsRayTracingPerComponentMotionInterpolation` | `char/BOOL` | 继承基类 |
| `supportsRayTracingPerPrimitiveData` | `char/BOOL` | 继承基类 |
| `supportsRayTracingTraversalMetrics` | `char/BOOL` | 继承基类 |
| `supportsRaytracing` | `char/BOOL` | 继承基类 |
| `supportsRaytracingFromRender` | `char/BOOL` | 继承基类 |
| `supportsReadWriteBufferArguments` | `char/BOOL` | 继承基类 |
| `supportsReadWriteTextureArguments` | `char/BOOL` | 继承基类 |
| `supportsReadWriteTextureArgumentsTier2` | `char/BOOL` | 继承基类 |
| `supportsReadWriteTextureCubeArguments` | `char/BOOL` | 继承基类 |
| `supportsRelaxedTextureViewRequirements` | `char/BOOL` | 继承基类 |
| `supportsRenderMemoryBarrier` | `char/BOOL` | 继承基类 |
| `supportsRenderPassWithoutRenderTarget` | `char/BOOL` | 继承基类 |
| `supportsRenderTargetTextureRotation` | `char/BOOL` | 继承基类 |
| `supportsRenderTextureWrites` | `char/BOOL` | 继承基类 |
| `supportsRenderToLinearTextures` | `char/BOOL` | 继承基类 |
| `supportsResourceDetachBacking` | `char/BOOL` | 继承基类 |
| `supportsSIMDGroup` | `char/BOOL` | 继承基类 |
| `supportsSIMDGroupMatrix` | `char/BOOL` | 继承基类 |
| `supportsSIMDReduction` | `char/BOOL` | 继承基类 |
| `supportsSIMDShuffleAndFill` | `char/BOOL` | 继承基类 |
| `supportsSIMDShufflesAndBroadcast` | `char/BOOL` | 继承基类 |
| `supportsSRGBwrites` | `char/BOOL` | 继承基类 |
| `supportsSamplerAddressModeClampToHalfBorder` | `char/BOOL` | 继承基类 |
| `supportsSamplerCompareFunction` | `char/BOOL` | 继承基类 |
| `supportsSamplerReductionMode` | `char/BOOL` | 继承基类 |
| `supportsSeparateDepthStencil` | `char/BOOL` | 继承基类 |
| `supportsSeparateVisibilityAndShadingRate` | `char/BOOL` | 继承基类 |
| `supportsSetThreadgroupPackingDisabled` | `char/BOOL` | 继承基类 |
| `supportsShaderBarycentricCoordinates` | `char/BOOL` | 继承基类 |
| `supportsShaderLODAverage` | `char/BOOL` | 继承基类 |
| `supportsShaderMinLODClamp` | `char/BOOL` | 继承基类 |
| `supportsSharedFunctionTables` | `char/BOOL` | 继承基类 |
| `supportsSharedStorageHeapResources` | `char/BOOL` | 继承基类 |
| `supportsSharedStorageTextures` | `char/BOOL` | 继承基类 |
| `supportsSparseDepthAttachments` | `char/BOOL` | 继承基类 |
| `supportsSparseHeaps` | `char/BOOL` | 继承基类 |
| `supportsSparseTextures` | `char/BOOL` | 继承基类 |
| `supportsStackOverflowErrorCode` | `char/BOOL` | 继承基类 |
| `supportsStencilFeedback` | `char/BOOL` | 继承基类 |
| `supportsStreamingCodecSignaling` | `char/BOOL` | 继承基类 |
| `supportsTLS` | `char/BOOL` | 继承基类 |
| `supportsTensors` | `char/BOOL` | 继承基类 |
| `supportsTessellation` | `char/BOOL` | 继承基类 |
| `supportsTexture2DMultisampleArray` | `char/BOOL` | 继承基类 |
| `supportsTextureAccessPatterns` | `char/BOOL` | 继承基类 |
| `supportsTextureCubeArray` | `char/BOOL` | 继承基类 |
| `supportsTextureOutOfBoundsReads` | `char/BOOL` | 继承基类 |
| `supportsTextureSampleCount:` | `char/BOOL` | 继承基类 |
| `supportsTextureSwizzle` | `char/BOOL` | 继承基类 |
| `supportsTextureWriteRoundingMode:` | `char/BOOL` | 继承基类 |
| `supportsTileShaders` | `char/BOOL` | 继承基类 |
| `supportsUnalignedVertexFetch` | `char/BOOL` | 继承基类 |
| `supportsVariableRateRasterization` | `char/BOOL` | 继承基类 |
| `supportsViewportAndScissorArray` | `char/BOOL` | 继承基类 |
| `supportsVirtualSubstreams` | `char/BOOL` | 继承基类 |
| `supportsWritableArrayOfTextures` | `char/BOOL` | 继承基类 |
| `supportsYCBCRFormats` | `char/BOOL` | 继承基类 |
| `supportsYCBCRFormats12` | `char/BOOL` | 继承基类 |
| `supportsYCBCRFormatsPQ` | `char/BOOL` | 继承基类 |
| `supportsYCBCRFormatsXR` | `char/BOOL` | 继承基类 |
| `supportsYCBCRPackedFormats12` | `char/BOOL` | 继承基类 |
| `supportsYCBCRPackedFormatsPQ` | `char/BOOL` | 继承基类 |
| `supportsYCBCRPackedFormatsXR` | `char/BOOL` | 继承基类 |
| `counterSets` | `id` | 继承基类 |
| `getDefaultSamplePositions:count:` | `void` | 继承基类 |
| `sampleTimestamps:gpuTimestamp:` | `void` | 继承基类 |
| `samplerReductionModeSupport` | `ulong long` | 继承基类 |
| `sizeOfCounterHeapEntry:` | `ulong long` | 继承基类 |
| `argumentBuffersSupport` | `ulong long` | 继承基类 |
| `bufferRobustnessSupport` | `ulong long` | 继承基类 |
| `commandBufferErrorOptions` | `ulong long` | 继承基类 |
| `defaultTextureWriteRoundingMode` | `long long` | 继承基类 |
| `functionHandleWithFunction:resourceIndex:` | `id` | 继承基类 |
| `heapAccelerationStructureSizeAndAlignWithDescriptor:` | `struct anon` | 继承基类 |
| `heapAccelerationStructureSizeAndAlignWithSize:` | `struct anon` | 继承基类 |
| `indirectArgumentBufferCapabilities` | `struct IndirectArgumentBufferCapabilities` | 继承基类 |
| `linearTextureArrayAlignmentSlice` | `ulong long` | 继承基类 |
| `minimumLinearTextureAlignmentForPixelFormat:` | `ulong long` | 继承基类 |
| `mtlTensorFromGpuResourceID:` | `id` | 继承基类 |
| `readWriteTextureSupport` | `ulong long` | 继承基类 |
| `requiredLinearTextureBytesPerRowForDescriptor:` | `ulong long` | 继承基类 |
| `sparseTexturesSupport` | `ulong long` | 继承基类 |
| `acceleratorPort` | `uint` | 继承家族 |
| `newAccelerationStructureWithBuffer:offset:` | `id` | 继承家族 |
| `newAccelerationStructureWithBuffer:offset:resourceIndex:` | `id` | 继承家族 |
| `newAccelerationStructureWithSize:` | `id` | 继承家族 |
| `newAccelerationStructureWithSize:resourceIndex:` | `id` | 继承家族 |
| `newAccelerationStructureWithSize:withDescriptor:` | `id` | 继承家族 |
| `newArgumentEncoderWithLayout:` | `id` | 继承家族 |
| `newEvent` | `id` | 继承家族 |
| `newEventWithOptions:` | `id` | 继承家族 |
| `newIOCommandQueueWithDescriptor:error:` | `id` | 继承家族 |
| `newIOFileHandleWithURL:compressionMethod:error:` | `id` | 继承家族 |
| `newIOFileHandleWithURL:error:` | `id` | 继承家族 |
| `newIOHandleWithURL:compressionMethod:error:` | `id` | 继承家族 |
| `newIOHandleWithURL:error:` | `id` | 继承家族 |
| `_deviceWrapper` | `id` | 继承家族 |
| `_setDeviceWrapper:` | `void` | 继承家族 |
| `supportsVertexAmplification` | `char/BOOL` | 继承家族 |

</details>

## 5. 可不实现的 optional

28 条。协议 optional 且三个类都没 IMP，即 Metal 不会假定它存在、参考实现也没提供。**第一版全部不实现。**

<details>
<summary>全部 28 条</summary>

| selector | 返回 |
|---|---|
| `getSurfaceMode:width:height:forId:` | `int` |
| `indirectArgumentBufferDecodingData` | `id` |
| `isSystemDefaultDevice` | `char/BOOL` |
| `mapShaderSampleBufferWithBuffer:capacity:size:` | `char/BOOL` |
| `newBufferWithBytes:length:options:gpuAddress:` | `id` |
| `newBufferWithBytesNoCopy:length:options:gpuAddress:deallocator:` | `id` |
| `newBufferWithDescriptor:` | `id` |
| `newBufferWithIOSurface:` | `id` |
| `newBufferWithLength:options:gpuAddress:` | `id` |
| `newGLDrawable` | `id` |
| `newIndirectArgumentEncoderWithArguments:` | `id` |
| `newIndirectArgumentEncoderWithLayout:` | `id` |
| `newLibraryWithCIFiltersForComputePipeline:imageFilterFunctionInfo:error:` | `id` |
| `newLibraryWithGraphs:functions:error:` | `id` |
| `newLibraryWithGraphsSPI:functions:error:` | `id` |
| `newMotionEstimationPipelineWithDescriptor:` | `id` |
| `newRenderPipelineStateWithTileDescriptor:completionHandler:` | `void` |
| `newRenderPipelineStateWithTileDescriptor:error:` | `id` |
| `newResourceGroupFromResources:count:` | `id` |
| `newTextureLayoutWithDescriptor:isHeapOrBufferBacked:` | `id` |
| `newTextureWithBytesNoCopy:length:descriptor:deallocator:` | `id` |
| `reserveGPUAddressRange:` | `char/BOOL` |
| `reserveResourceIndicesForResourceType:indices:indexCount:` | `void` |
| `resourcePatchingTypeForResourceType:` | `ulong long` |
| `setIndirectArgumentBufferDecodingData:` | `void` |
| `setupMPSFunctionTable:` | `void` |
| `tileSizeWithSparsePageSize:textureType:pixelFormat:sampleCount:` | `struct anon` |
| `unmapShaderSampleBuffer` | `void` |

</details>

## 6. 重新生成

```powershell
# 1) 取运行期转储
gh workflow run evidence-macos26-intel.yml --ref main
$id = gh run list --workflow=evidence-macos26-intel.yml --limit 1 --json databaseId --jq '.[0].databaseId'
gh run download $id --dir ci-evidence

# 2) 重新生成本文
py tools\ci\gen_device_spi_table.py ci-evidence\objc-dump\objc-dump.json docs\spec\23-DEVICE-SPI-DISPOSITION.md
```

**本文不要手改。** 要改判定规则就改 `tools/ci/gen_device_spi_table.py` 的 `disposition()`，这样规则本身是可 review、可 diff 的。
