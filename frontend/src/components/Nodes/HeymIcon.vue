<script setup lang="ts">
/**
 * The Heym brand mark, used as the node icon for `heym` and `heymTrigger`.
 *
 * Kept in sync with `public/fav.svg`. The gradient needs a document-unique id:
 * SVG ids share one namespace across the whole page, so several nodes on the
 * canvas rendering the same literal id would be invalid markup.
 */
let instanceCount = 0;
const gradientId = `heym-node-icon-gradient-${(instanceCount += 1)}`;
</script>

<template>
  <!--
    Sized by whatever class the call site passes, exactly like the lucide icons it
    sits beside. It must never force its own size: the expression dialog renders
    node icons in a flex row with no height constraint, so a hardcoded 100% grew
    this mark to fill the whole dialog. Sites that want it to fill a tile ask for
    that themselves - see `isTileFillingIcon`.

    The viewBox is padded past the 32-unit artwork so the tile sits inside its
    container rather than running to the edges: filling a tile exactly made a
    saturated square read as larger than the faint tinted squares beside it. `rx`
    then keeps the corner radius at ~28% of the tile, the proportion the
    containers use, so it reads as the same shape family.
  -->
  <svg
    viewBox="-3 -3 38 38"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
    focusable="false"
  >
    <defs>
      <linearGradient
        :id="gradientId"
        x1="0%"
        y1="0%"
        x2="100%"
        y2="100%"
      >
        <stop
          offset="0%"
          stop-color="#8B5CF6"
        />
        <stop
          offset="100%"
          stop-color="#6366F1"
        />
      </linearGradient>
    </defs>
    <rect
      width="32"
      height="32"
      rx="9"
      :fill="`url(#${gradientId})`"
    />
    <path
      d="M8 16h6M18 16h6M14 10v12M18 10v12"
      stroke="white"
      stroke-width="2"
      stroke-linecap="round"
    />
  </svg>
</template>
