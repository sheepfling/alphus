export default [
  {
    files: ["javascript/**/*.js"],
    rules: {
      complexity: ["error", { max: 10, variant: "classic" }],
    },
  },
];
