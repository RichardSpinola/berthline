public class Quick {
    public static void main(String[] args) {
        long total = 0;
        for (int i = 0; i < 50_000_000; i++) {
            total += i % 7;
        }
        System.out.println("total " + total);
    }
}
